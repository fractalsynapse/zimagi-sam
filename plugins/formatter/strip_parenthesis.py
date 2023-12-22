from systems.plugins.index import BaseProvider


class Provider(BaseProvider('formatter', 'strip_parenthesis')):

    def format(self, value, record):
        value = super().format(value, record)
        if value:
            value = value.removeprefix('(').removesuffix(')')
        return value
