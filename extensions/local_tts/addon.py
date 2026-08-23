from ten_runtime import Addon, TenEnv, register_addon_as_extension


@register_addon_as_extension("local_tts")
class LocalTTSAddon(Addon):
    def on_create_instance(self, ten_env: TenEnv, name: str, context) -> None:
        from .extension import LocalTTSExtension

        ten_env.on_create_instance_done(LocalTTSExtension(name), context)
