"""Payload-free request attempt evidence, separate from the no-replay dispatch ledger."""
import asyncio
import json
import logging
import math
import re
import sqlite3
import time

from fastapi import HTTPException, Query, Response
from starlette.datastructures import Headers

LOG = logging.getLogger(__name__)
RETENTION_SECONDS = 7 * 86400
CLASS_LIMIT = 10000
REASONS = set("no_ready_target demo_run_not_active node_route_changed body_too_large JSON_object_or_contract_required common_request_or_target_invalid request_id_payload_conflict request_in_progress request_id_pending queue_full demo_stopped_before_dispatch route_unavailable io_contract_changed common_target_changed inference_contract_changed admission_timeout worker_outcome_unknown controller_restarted_outcome_unknown".split())


class Recorder:
    def __init__(self, journal):
        self.db = journal.db
        self.last_prune = 0
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS request_diagnostics(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL, request_id TEXT NOT NULL,
            run_id TEXT, at REAL NOT NULL, terminal INTEGER NOT NULL DEFAULT 0,
            failure INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS diagnostics_service ON request_diagnostics(uid,seq DESC);
          CREATE INDEX IF NOT EXISTS diagnostics_failures ON request_diagnostics(uid,failure,seq DESC);
          CREATE INDEX IF NOT EXISTS diagnostics_retention ON request_diagnostics(terminal,failure,seq DESC);
        """)
        with self.db:
            for seq, raw in self.db.execute("SELECT seq,body FROM request_diagnostics WHERE terminal=0").fetchall():
                value = json.loads(raw)
                dispatched = value['state'] == 'dispatched'
                value.update(state='unknown' if dispatched else 'interrupted',
                    reason='controller_restarted_after_dispatch' if dispatched else 'controller_restarted_before_dispatch',
                    finishedAt=time.time())
                self.db.execute("UPDATE request_diagnostics SET terminal=1,failure=1,body=? WHERE seq=?",
                                (json.dumps(value), seq))
        self.prune()

    def prune(self):
        now = time.time()
        if now - self.last_prune < 60:
            return
        with self.db:
            self.db.execute("DELETE FROM request_diagnostics WHERE terminal=1 AND at<?", (now-RETENTION_SECONDS,))
            for failure in (0, 1):
                self.db.execute("DELETE FROM request_diagnostics WHERE seq IN (SELECT seq FROM request_diagnostics WHERE terminal=1 AND failure=? ORDER BY seq DESC LIMIT -1 OFFSET ?)", (failure, CLASS_LIMIT))
        self.last_prune = now

    def start(self, value):
        self.prune()
        with self.db:
            row = self.db.execute("INSERT INTO request_diagnostics(uid,request_id,run_id,at,body) VALUES(?,?,?,?,?)",
                (value['uid'], value['requestId'], value['runId'], value['startedAt'], json.dumps(value)))
        value['seq'] = row.lastrowid

    def save(self, value, terminal=False):
        failure = terminal and (value['state'] in ('unknown', 'interrupted') or
            value['state'] != 'cancelled' and (value.get('status') or 0) >= 400)
        with self.db:
            self.db.execute("UPDATE request_diagnostics SET terminal=?,failure=?,body=? WHERE seq=?",
                            (int(terminal), int(failure), json.dumps(value), value['seq']))

    def list(self, uid, *, limit=25, before=None, failures_only=True, run_id=None):
        clauses, args = ['uid=?', 'at>=?'], [uid, time.time()-RETENTION_SECONDS]
        if failures_only:
            clauses.append('failure=1')
        if before is not None:
            clauses.append('seq<?'); args.append(before)
        if run_id:
            clauses.append('run_id=?'); args.append(run_id)
        rows = self.db.execute('SELECT seq,body FROM request_diagnostics WHERE '+
            ' AND '.join(clauses)+' ORDER BY seq DESC LIMIT ?', (*args, limit+1)).fetchall()
        values = [json.loads(raw) | {'seq': seq} for seq, raw in rows[:limit]]
        return {'items': values, 'nextBefore': values[-1]['seq'] if len(rows)>limit else None,
                'observedAt': time.time(), 'retentionSeconds': RETENTION_SECONDS,
                'retainedPerOutcomeClass': CLASS_LIMIT, 'failuresOnly': failures_only}


def recorder(controller):
    if not hasattr(controller, 'request_diagnostics'):
        controller.request_diagnostics = Recorder(controller.journal)
    return controller.request_diagnostics


class Attempt:
    def __init__(self, store, uid, request_id, run_id, active):
        self.store, self.started = store, time.monotonic()
        self.queue_started = self.dispatched = None
        self.worker_finished = None
        self.value = dict(uid=uid, requestId=request_id, runId=run_id, startedAt=time.time(),
            finishedAt=None, state='receiving', status=None, reason=None, replay=False,
            admittedNode=(active or {}).get('node'), node=None, revision=None,
            gatewayQueueMilliseconds=None, workerRoundTripMilliseconds=None,
            workerQueueMilliseconds=None, inferenceMilliseconds=None, totalMilliseconds=None,
            upstreamStatus=None)
        store.start(self.value)

    def persist(self, terminal=False):
        try:
            self.store.save(self.value, terminal)
        except sqlite3.Error:
            LOG.error('request_diagnostic_write_failed')

    def queued(self):
        self.queue_started = time.monotonic()
        self.value['state'] = 'queued'
        self.persist()

    def dispatch(self, target):
        self.dispatched = time.monotonic()
        self.value.update(state='dispatched', node=target['node'], revision=target['name'],
            gatewayQueueMilliseconds=(self.dispatched-self.queue_started)*1000 if self.queue_started else 0)
        self.persist()

    def finish(self, status, state, reason):
        now = time.monotonic()
        if self.queue_started is not None and self.dispatched is None:
            self.value['gatewayQueueMilliseconds'] = (now-self.queue_started)*1000
        if self.dispatched is not None:
            self.value['workerRoundTripMilliseconds'] = ((self.worker_finished or now)-self.dispatched)*1000
        self.value.update(status=status, state=state, finishedAt=time.time(), totalMilliseconds=(now-self.started)*1000)
        self.value['reason'] = self.value['reason'] or reason
        self.persist(terminal=True)


def mark(request, event, value=None):
    attempt = request.scope.get('runtime_diagnostic')
    if not attempt:
        return
    if event == 'queued': attempt.queued()
    elif event == 'dispatch': attempt.dispatch(value)
    elif event == 'replay': attempt.value.update(replay=True, revision=value['target'])
    elif event == 'worker_finished': attempt.worker_finished = time.monotonic()
    elif event == 'failure': attempt.value.update(reason=value[0], upstreamStatus=value[1])
    elif event == 'metrics':
        for source, dest in [('queue_wait_ms','workerQueueMilliseconds'), ('inference_ms','inferenceMilliseconds')]:
            number = value.get(source) if isinstance(value, dict) else None
            if isinstance(number, (int,float)) and not isinstance(number,bool) and math.isfinite(number) and number>=0:
                attempt.value[dest] = number


class DiagnosticsMiddleware:
    def __init__(self, app, controller_getter):
        self.app, self.controller_getter = app, controller_getter

    async def __call__(self, scope, receive, send):
        match = re.fullmatch(r'/services/([a-z0-9-]{1,63})/invoke', scope.get('path',''))
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not match:
            return await self.app(scope, receive, send)
        c, headers = self.controller_getter(), Headers(scope=scope)
        request_id = headers.get('x-request-id','')
        services = [s for s in c.states.values() if s['name']==match[1] and s.get('phase') not in ('Deleted','Missing')] if c else []
        if (len(services)!=1 or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', request_id)
                or headers.get('x-runtime-service-uid',services[0]['uid'])!=services[0]['uid']):
            return await self.app(scope, receive, send)
        service = services[0]
        run_id = headers.get('x-runtime-demo-run')
        if run_id and not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',run_id): run_id=None
        try:
            attempt = Attempt(recorder(c),service['uid'],request_id,run_id,service.get('active'))
        except sqlite3.Error:
            LOG.error('request_diagnostic_unavailable')
            return await self.app(scope, receive, send)
        scope['runtime_diagnostic'] = attempt
        status, outcome, body = 500, 'unknown', bytearray()
        async def capture(message):
            nonlocal status, outcome
            if message['type']=='http.response.start':
                status = message['status']
                outcome = Headers(raw=message.get('headers',[])).get('x-request-state',
                    'completed' if 200<=status<300 else 'rejected')
            elif message['type']=='http.response.body' and status>=400 and len(body)<16384:
                body.extend(message.get('body',b'')[:16384-len(body)])
            await send(message)
        try:
            await self.app(scope, receive, capture)
        except asyncio.CancelledError:
            attempt.finish(None, 'unknown' if attempt.dispatched else 'interrupted', 'request_cancelled')
            raise
        except Exception:
            attempt.finish(500, 'unknown' if attempt.dispatched else 'interrupted', 'gateway_exception')
            raise
        else:
            reason = 'completed' if 200<=status<300 else 'worker_http_error' if attempt.dispatched else 'gateway_rejected'
            if not attempt.dispatched or outcome=='unknown':
                try:
                    code=json.loads(body).get('reason')
                    if isinstance(code,str) and code in REASONS: reason=code
                except (ValueError,AttributeError): pass
            attempt.finish(status,outcome,reason)


def install(app):
    app.add_middleware(DiagnosticsMiddleware, controller_getter=lambda: app.state.controller)

    @app.get('/services/{name}/request-diagnostics')
    async def history(name: str, response: Response,
                      serviceUid: str = Query(pattern=r'^[A-Za-z0-9-]{1,80}$'),
                      limit: int = Query(default=25,ge=1,le=100), before: int | None = Query(default=None,ge=1),
                      failuresOnly: bool = True, runId: str | None = Query(default=None,pattern=r'^[A-Za-z0-9_-]{8,80}$')):
        c=app.state.controller
        if not any(s['uid']==serviceUid and s['name']==name for s in c.states.values()):
            raise HTTPException(404,'service_identity_not_found')
        response.headers['Cache-Control']='no-store'
        try:
            return recorder(c).list(serviceUid,limit=limit,before=before,failures_only=failuresOnly,run_id=runId)
        except sqlite3.Error:
            raise HTTPException(503,'request_diagnostic_unavailable') from None
