from abc import ABC, abstractmethod


class KrittikaNoC(ABC):

    @abstractmethod
    def __init__(self, NetworkConfig):
        pass

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def post(self, clk, src, dest, data_size) -> int:
        # Posts a data_size txn from src to dest at time clk
        # Returns tracking_id of this txn
        # Internally registers this tracking ID with the txn Event to be sent
        pass

    @abstractmethod
    def deliver_all_txns(self):
        # Simulates all the txns that need to be sent so latency can be arrived at
        pass

    @abstractmethod
    def get_latency(self, tracking_id) -> int:
        # After delivery is done, query the latency of a txn using tracking_id
        pass

    @abstractmethod
    def get_static_latency(self, src, dest, size) -> int:
        # Returns the fixed part of sending from src to dest
        #   This includes serialization delay and fixed route latency
        pass
