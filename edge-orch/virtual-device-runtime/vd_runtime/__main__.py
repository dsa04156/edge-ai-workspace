import os
import uvicorn
from .api import create_app

app = create_app()


class DrainingServer(uvicorn.Server):
    def handle_exit(self, sig, frame):
        app.state.runtime.draining = True
        super().handle_exit(sig, frame)


if __name__ == "__main__":
    DrainingServer(uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")),
                                 workers=1, timeout_graceful_shutdown=25)).run()
