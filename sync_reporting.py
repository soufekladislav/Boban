"""Human-readable read-only reporting of scheduled analytics sync state."""
from datetime import datetime, timedelta


def status_label(connected, enabled, last_run=None, last_status=None, due=False, last_error=None):
    if not connected:return 'NOT_CONNECTED – konektor není připojen'
    if not enabled:return 'DISABLED – automatické synchronizace projektu jsou vypnuté'
    if last_status=='failed':
        detail=(last_error or 'nezjištěná chyba').replace('\n',' ')[:160]
        return 'ERROR – poslední běh selhal: '+detail
    if not due:
        return 'SKIPPED – interval ještě neuplynul; poslední běh '+str(last_run or 'není znám')
    return 'DUE – synchronizace je splatná, ale v tomto běhu se neprovedla (ověř konfiguraci)'


def summary(wb,projects):
    names=[('GA4','ga4','ga4_sync',12),('GSC','search_console','search_console_sync',12),('GTM','gtm','gtm_sync',24)]
    lines=[]
    for project in projects:
        pid=project['id']
        enabled=wb.project_automation_allowed(pid)
        for display,provider,rule,hours in names:
            conn_row=wb.integration_row(pid,provider)
            connected=bool(conn_row and conn_row['status']=='connected')
            conn=wb.db()
            try:
                state=conn.execute('SELECT last_run,last_status,last_error FROM automation_state WHERE project_id=? AND rule_key=?',(pid,rule)).fetchone()
            finally:conn.close()
            due=bool(connected and enabled and wb.automation_rule_due(pid,rule,hours))
            label=status_label(connected,enabled,state['last_run'] if state else None,
                               state['last_status'] if state else None,due,
                               state['last_error'] if state else None)
            lines.append(f'project {pid} / {display}: {label}')
    return lines
