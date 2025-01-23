import json

import redis
from .schemas import CustomSchemaBase, SessionSchema, SessionAuthSchema


class SessionEncoder(json.JSONEncoder):
    _classes = {"SessionSchema": SessionSchema, "SessionAuthSchema": SessionAuthSchema}

    def default(self, o):
        if isinstance(o, CustomSchemaBase):
            return {"_cls_name_": o.__class__.__name__, "__value__": o.__dict__}

        return super().default(o)

    @staticmethod
    def decode_hook(d):
        if "_cls_name_" in d:
            class_name = d.pop("_cls_name_")
            class_ = SessionEncoder._classes.get(class_name)
            if class_ is None:
                raise ValueError(f"Unknown class name: {class_name}")
            return class_(**d["__value__"])
        return d


class RedisCrud:
    def __init__(self, db: int):
        self.connect = redis.Redis(host="redis", port=6379, db=db)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connect.close()

    def get(self, key: str):
        data = self.connect.get(key)
        if data is None:
            return None
        return SessionSchema(**json.loads(data, object_hook=SessionEncoder.decode_hook))

    def set(self, key: str, value: any, expire: int = None):
        if expire is not None:
            return self.connect.set(
                key, json.dumps(value.__dict__, cls=SessionEncoder), ex=expire
            )

        return self.connect.set(key, json.dumps(value.__dict__, cls=SessionEncoder))

    def delete(self, key: str):
        return self.connect.delete(key)
