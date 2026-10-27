"""咪咕 2.3–2.6 故事链集锦 HTTP 协议层（薄封装，不改 algo 核心）。"""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from api.app import app

        return app
    raise AttributeError(name)
