"""券商介面（Iteration 58）：引擎只認 Broker 的四個方法，紙上與凱基各自實作。"""
from .base import Broker, BrokerNotConfigured, Fill
from .paper import PaperBroker
from .kgi import KgiBroker


def make_broker(name: str) -> Broker:
    if name == 'paper':
        return PaperBroker()
    if name == 'kgi':
        return KgiBroker()
    raise ValueError(f'不認識的券商：{name}')


__all__ = ['Broker', 'BrokerNotConfigured', 'Fill', 'PaperBroker', 'KgiBroker', 'make_broker']
