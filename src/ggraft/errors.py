"""Error hierarchy. Messages are printed verbatim by the CLI."""


class GgraftError(Exception): ...


class ConfigError(GgraftError): ...          # ggraft.toml missing or malformed
class PatchError(GgraftError): ...           # patch file malformed
class TargetError(GgraftError): ...          # target unresolvable against the base
class PullError(GgraftError): ...            # base could not be fetched


class InjectionError(GgraftError):
    def __init__(self, where: str, detail: str) -> None:
        super().__init__(f"{where}: {detail}")
        self.where = where                   # "<patch>[<index>] -> <target>"
        self.detail = detail


class UnresolvedInjection(InjectionError): ...   # anchor matched nothing
class AmbiguousInjection(InjectionError): ...    # anchor matched more than once
