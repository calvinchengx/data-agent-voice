from ten_runtime import Addon, TenEnv, register_addon_as_extension


@register_addon_as_extension("das_tools")
class DasToolsAddon(Addon):
    def on_create_instance(self, ten_env: TenEnv, name: str, context) -> None:
        from .extension import DasToolsExtension

        ten_env.on_create_instance_done(DasToolsExtension(name), context)
