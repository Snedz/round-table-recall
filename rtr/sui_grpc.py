"""Second Tatum Sui interface: gRPC (``sui.rpc.v2.LedgerService``) on ``sui-<network>-grpc.gateway.tatum.io``.

Used to cross-check the GraphQL proof: the ``MemWalAccount`` object read over
gRPC must have the same version and digest as the one read over GraphQL.
Message types come from server reflection, so no generated stubs are needed.
Optional: needs ``grpcio``, ``grpcio-reflection`` and ``protobuf``.
"""

from __future__ import annotations

from . import config

TATUM_GRPC = {"mainnet": "sui-mainnet-grpc.gateway.tatum.io:443", "testnet": "sui-testnet-grpc.gateway.tatum.io:443"}


class TatumSuiGrpc:
    def __init__(self, network: str | None = None, timeout: float = 20.0):
        import grpc
        from google.protobuf.descriptor_pool import DescriptorPool
        from grpc_reflection.v1alpha.proto_reflection_descriptor_database import ProtoReflectionDescriptorDatabase

        self.network = network or config.network()
        self.key = config.get(f"TATUM_API_KEY_{self.network.upper()}")
        if not self.key:
            raise RuntimeError("Tatum API key not configured")
        self.target = TATUM_GRPC[self.network]
        self.timeout = timeout
        self.channel = grpc.secure_channel(self.target, grpc.ssl_channel_credentials())
        self.pool = DescriptorPool(ProtoReflectionDescriptorDatabase(self.channel))

    def call(self, service: str, method: str, request: dict) -> dict:
        from google.protobuf import json_format, message_factory

        m = self.pool.FindServiceByName(service).methods_by_name[method]
        req_cls = message_factory.GetMessageClass(m.input_type)
        resp_cls = message_factory.GetMessageClass(m.output_type)
        rpc = self.channel.unary_unary(f"/{service}/{method}", request_serializer=req_cls.SerializeToString,
                                       response_deserializer=resp_cls.FromString)
        import time

        import grpc

        msg = json_format.ParseDict(request, req_cls())
        for attempt in range(5):  # the free Tatum plan allows 3 requests/s; back off on 429
            try:
                resp = rpc(msg, metadata=[("x-api-key", self.key)], timeout=self.timeout)
                return json_format.MessageToDict(resp)
            except grpc.RpcError as e:
                if "429" not in str(e.details() if hasattr(e, "details") else e) or attempt == 4:
                    raise
                time.sleep(1.0 * (2 ** attempt))
        raise RuntimeError("unreachable")

    def service_info(self) -> dict:
        return self.call("sui.rpc.v2.LedgerService", "GetServiceInfo", {})

    def get_object(self, object_id: str) -> dict:
        r = self.call("sui.rpc.v2.LedgerService", "GetObject",
                      {"objectId": object_id, "readMask": "objectId,version,digest,objectType,json"})
        return r.get("object", {})


def cross_check(graphql_version: str, graphql_digest: str, grpc_object: dict) -> tuple[bool, str]:
    """Do both Tatum interfaces agree on the account object's version and digest?"""
    v, d = str(grpc_object.get("version", "")), str(grpc_object.get("digest", ""))
    ok = bool(v) and v == str(graphql_version) and d == str(graphql_digest)
    return ok, f"gRPC version/digest {v or '-'} / {d or '-'} " + ("match GraphQL" if ok else "DO NOT match GraphQL")
