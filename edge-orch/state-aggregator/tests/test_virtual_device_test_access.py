import hashlib
import hmac
from app.virtual_device_test_access import issue, verify


def test_capability_expires_and_never_equals_operator_key():
    token=issue('operator-secret',now=1000)
    assert verify(token,'operator-secret',now=1001)
    assert not verify(token,'operator-secret',now=87400)
    assert not verify(token,'operator-secret',now=999)
    assert not hmac.compare_digest(token,'operator-secret')


def test_tampering_other_signer_and_other_scope_are_rejected():
    token=issue('operator-secret',now=1000)
    assert not verify(token,'another-secret',now=1001)
    assert not verify(token.replace('87400','87401'),'operator-secret',now=1001)
    head=token.rsplit('.',1)[0]
    foreign=head+'.'+hmac.new(b'operator-secret',('another-device:start,infer,stop:'+head).encode(),hashlib.sha256).hexdigest()
    assert not verify(foreign,'operator-secret',now=1001)


def test_malformed_tokens_do_not_raise():
    for value in [None,'', 'x'*1000, 'vdtest.87400.'+'a'*32+'.'+'한'*64,'vdtest.no-number.a.b']:
        assert not verify(value,'operator-secret',now=1001)
