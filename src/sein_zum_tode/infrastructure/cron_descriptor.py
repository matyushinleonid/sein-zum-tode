from cron_descriptor import Options, get_description


class CronDescriptor:
    def describe(self, expression: str, locale: str) -> str:
        return str(get_description(expression, Options(locale_code=locale)))
