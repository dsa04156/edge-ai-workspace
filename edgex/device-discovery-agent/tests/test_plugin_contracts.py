from app.plugins import EXTENSION_PLUGINS


def test_unimplemented_plugins_never_return_fake_candidates():
    for plugin in EXTENSION_PLUGINS.values():
        result = plugin.discover({"enabled": True, "endpoints": ["allowed"]})
        assert result.observations == []
        assert result.implementation_state == "not-implemented"
        assert result.errors
