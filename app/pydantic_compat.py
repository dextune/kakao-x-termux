from __future__ import annotations

"""pydantic v2 API를 v1/v2 양쪽에서 쓸 수 있게 감싸는 호환층이다."""

from typing import Any, Callable

try:  # pydantic v2
    from pydantic import BaseModel as _BaseModel
    from pydantic import ConfigDict, Field, ValidationError, model_validator

    PYDANTIC_V2 = True

    class BaseModel(_BaseModel):
        """pydantic v2의 BaseModel을 그대로 노출한다."""

        pass

except ImportError:  # pydantic v1
    from pydantic import BaseModel as _BaseModel
    from pydantic import Field, ValidationError, root_validator

    PYDANTIC_V2 = False

    def ConfigDict(**kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)

    class BaseModel(_BaseModel):
        """pydantic v1에서 v2 호환 메서드를 제공하는 BaseModel이다."""

        class Config:
            arbitrary_types_allowed = True
            use_enum_values = True

        @classmethod
        def model_validate(cls, obj: Any) -> "BaseModel":
            return cls.parse_obj(obj)

        @classmethod
        def model_validate_json(cls, data: str) -> "BaseModel":
            return cls.parse_raw(data)

        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            kwargs.pop("mode", None)
            return self.dict(*args, **kwargs)

        def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
            kwargs.pop("mode", None)
            return self.json(*args, **kwargs)

        def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> "BaseModel":
            return self.copy(update=update or {}, deep=deep)

    def model_validator(*, mode: str = "after") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if mode != "after":
            raise NotImplementedError("pydantic v1 compatibility only supports mode='after'")

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @root_validator(pre=False, allow_reuse=True)
            def _wrapper(cls, values):
                obj = cls.construct(**values)
                result = func(obj)
                if result is None:
                    result = obj
                if isinstance(result, cls):
                    return result.dict()
                if hasattr(result, "dict"):
                    return result.dict()
                return values

            return _wrapper

        return decorator
