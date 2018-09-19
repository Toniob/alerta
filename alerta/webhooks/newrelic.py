from flask import jsonify, request
from flask_cors import cross_origin

from alerta.auth.decorators import permission
from alerta.exceptions import ApiError, RejectException
from alerta.models.alert import Alert
from alerta.models.enums import Status
from alerta.models.severity import Severity
from alerta.utils.api import add_remote_ip, assign_customer, process_alert

from . import webhooks


def parse_newrelic(alert):

    if 'version' not in alert:
        raise ValueError('New Relic Legacy Alerting is not supported')

    status = Status.from_str(alert['current_state'])
    severity = Severity.from_str(alert['severity'])

    if status == 'acknowledged':
        status = Status.ACK
    elif status == 'closed':
        severity = Severity.OK
    elif alert['severity'].lower() == 'info':
        severity = Severity.INFORMATIONAL
        status = Status.OPEN
    else:
        status = Status.OPEN

    attributes = dict()
    if 'incident_url' in alert:
        attributes['moreInfo'] = '<a href="%s" target="_blank">Incident URL</a>' % alert['incident_url']
    if 'runbook_url' in alert:
        attributes['runBook'] = '<a href="%s" target="_blank">Runbook URL</a>' % alert['runbook_url']

    return Alert(
        resource=alert['targets'][0]['name'],
        event=alert['condition_name'],
        environment='Production',
        severity=severity,
        status=status,
        service=[alert['account_name']],
        group=alert['targets'][0]['type'],
        text=alert['details'],
        tags=['{}:{}'.format(key, value) for (key, value) in alert['targets'][0]['labels'].items()],
        attributes=attributes,
        origin='New Relic/v%s' % alert['version'],
        event_type=alert['event_type'].lower(),
        raw_data=alert
    )


@webhooks.route('/webhooks/newrelic', methods=['OPTIONS', 'POST'])
@cross_origin()
@permission('write:webhooks')
def newrelic():

    try:
        incomingAlert = parse_newrelic(request.json)
    except ValueError as e:
        raise ApiError(str(e), 400)

    incomingAlert.customer = assign_customer(wanted=incomingAlert.customer)
    add_remote_ip(request, incomingAlert)

    try:
        alert = process_alert(incomingAlert)
    except RejectException as e:
        raise ApiError(str(e), 403)
    except Exception as e:
        raise ApiError(str(e), 500)

    if alert:
        return jsonify(status='ok', id=alert.id, alert=alert.serialize), 201
    else:
        raise ApiError('insert or update of New Relic alert failed', 500)
