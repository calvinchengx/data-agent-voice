from ten_runtime import Addon, TenEnv, register_addon_as_extension


@register_addon_as_extension("das_host")
class DasHostAddon(Addon):
    def on_create_instance(self, ten_env: TenEnv, name: str, context) -> None:
        from .extension import DasHostExtension

        ten_env.on_create_instance_done(DasHostExtension(name), context)
