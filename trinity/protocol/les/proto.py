from typing import (
    Any,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Tuple,
    TYPE_CHECKING,
    Union,
)

from lahja import (
    BroadcastConfig,
    EndpointAPI,
)

from eth_typing import (
    BlockNumber,
    Hash32,
)

from eth_utils import (
    to_dict,
    ValidationError,
)

from eth.rlp.headers import BlockHeader

from p2p.abc import SessionAPI
from p2p.protocol import Protocol
from p2p.typing import Payload

from trinity._utils.les import gen_request_id

from .commands import (
    Status,
    StatusV2,
    Announce,
    BlockHeaders,
    GetBlockBodies,
    GetBlockHeaders,
    GetBlockHeadersQuery,
    GetContractCodes,
    GetProofs,
    GetProofsV2,
    GetReceipts,
    BlockBodies,
    Receipts,
    Proofs,
    ProofsV2,
    ProofRequest,
    ContractCodeRequest,
    ContractCodes,
)
from .events import SendBlockHeadersEvent
from . import constants

if TYPE_CHECKING:
    from .peer import LESPeer  # noqa: F401


class LESHandshakeParams(NamedTuple):
    version: int
    network_id: int
    head_td: int
    head_hash: Hash32
    head_number: BlockNumber
    genesis_hash: Hash32
    serve_headers: bool
    serve_chain_since: Optional[BlockNumber]
    serve_state_since: Optional[BlockNumber]
    serve_recent_state: Optional[bool]
    serve_recent_chain: Optional[bool]
    tx_relay: bool
    flow_control_bl: Optional[int]
    flow_control_mcr: Optional[Tuple[Tuple[int, int, int], ...]]
    flow_control_mrr: Optional[int]
    announce_type: Optional[int]

    def as_payload_dict(self) -> Payload:
        return self._as_payload_dict()

    @to_dict
    def _as_payload_dict(self) -> Iterable[Tuple[str, Any]]:
        yield 'protocolVersion', self.version
        yield 'networkId', self.network_id
        yield 'headTd', self.head_td
        yield 'headHash', self.head_hash
        yield 'headNum', self.head_number
        yield 'genesisHash', self.genesis_hash
        if self.serve_headers is True:
            yield 'serveHeaders', None
        if self.serve_chain_since is not None:
            yield 'serveChainSince', self.serve_chain_since
        if self.serve_state_since is not None:
            yield 'serveStateSince', self.serve_state_since
        if self.serve_recent_chain is not None:
            yield 'serveRecentChain', self.serve_recent_chain
        if self.serve_recent_state is not None:
            yield 'serveRecentState', self.serve_recent_state
        if self.tx_relay is True:
            yield 'txRelay', None
        if self.flow_control_bl is not None:
            yield "flowControl/BL", self.flow_control_bl
        if self.flow_control_mcr is not None:
            yield "flowControl/MRC", self.flow_control_mcr
        if self.flow_control_mrr is not None:
            yield "flowControl/MRR", self.flow_control_mrr
        if self.announce_type is not None:
            yield "announceType", self.announce_type


class LESProtocol(Protocol):
    name = 'les'
    version = 1
    _commands = (
        Status,
        Announce,
        BlockHeaders, GetBlockHeaders,
        BlockBodies,
        Receipts,
        Proofs,
        ContractCodes,
    )
    cmd_length = 15
    peer: 'LESPeer'

    def send_handshake(self, handshake_params: LESHandshakeParams) -> None:
        if handshake_params.version != self.version:
            raise ValidationError(
                f"LES protocol version mismatch: "
                f"params:{handshake_params.version} != proto:{self.version}"
            )
        resp = handshake_params.as_payload_dict()
        cmd = Status(self.cmd_id_offset, self.snappy_support)
        self.transport.send(*cmd.encode(resp))
        self.logger.debug("Sending LES/Status msg: %s", resp)

    def send_get_block_bodies(self, block_hashes: List[bytes], request_id: int=None) -> int:
        if request_id is None:
            request_id = gen_request_id()
        if len(block_hashes) > constants.MAX_BODIES_FETCH:
            raise ValueError(
                f"Cannot ask for more than {constants.MAX_BODIES_FETCH} blocks in a single request"
            )
        data = {
            'request_id': request_id,
            'block_hashes': block_hashes,
        }
        header, body = GetBlockBodies(self.cmd_id_offset, self.snappy_support).encode(data)
        self.transport.send(header, body)

        return request_id

    def send_get_block_headers(
            self,
            block_number_or_hash: Union[BlockNumber, Hash32],
            max_headers: int,
            skip: int,
            reverse: bool,
            request_id: int=None) -> int:
        """Send a GetBlockHeaders msg to the remote.

        This requests that the remote send us up to max_headers, starting from
        block_number_or_hash if reverse is False or ending at block_number_or_hash if reverse is
        True.
        """
        if request_id is None:
            request_id = gen_request_id()
        cmd = GetBlockHeaders(self.cmd_id_offset, self.snappy_support)
        data = {
            'request_id': request_id,
            'query': GetBlockHeadersQuery(
                block_number_or_hash,
                max_headers,
                skip,
                reverse,
            ),
        }
        header, body = cmd.encode(data)
        self.transport.send(header, body)

        return request_id

    def send_block_headers(
            self, headers: Tuple[BlockHeader, ...], buffer_value: int, request_id: int=None) -> int:
        if request_id is None:
            request_id = gen_request_id()
        data = {
            'request_id': request_id,
            'headers': headers,
            'buffer_value': buffer_value,
        }
        header, body = BlockHeaders(self.cmd_id_offset, self.snappy_support).encode(data)
        self.transport.send(header, body)

        return request_id

    def send_get_receipts(self, block_hash: bytes, request_id: int=None) -> int:
        if request_id is None:
            request_id = gen_request_id()
        data = {
            'request_id': request_id,
            'block_hashes': [block_hash],
        }
        header, body = GetReceipts(self.cmd_id_offset, self.snappy_support).encode(data)
        self.transport.send(header, body)

        return request_id

    def send_get_proof(self, block_hash: bytes, account_key: bytes, key: bytes, from_level: int,
                       request_id: int=None) -> int:
        if request_id is None:
            request_id = gen_request_id()
        data = {
            'request_id': request_id,
            'proof_requests': [ProofRequest(block_hash, account_key, key, from_level)],
        }
        header, body = GetProofs(self.cmd_id_offset, self.snappy_support).encode(data)
        self.transport.send(header, body)

        return request_id

    def send_get_contract_code(self, block_hash: bytes, key: bytes, request_id: int=None) -> int:
        if request_id is None:
            request_id = gen_request_id()
        data = {
            'request_id': request_id,
            'code_requests': [ContractCodeRequest(block_hash, key)],
        }
        header, body = GetContractCodes(self.cmd_id_offset, self.snappy_support).encode(data)
        self.transport.send(header, body)

        return request_id


class LESProtocolV2(LESProtocol):
    version = 2
    _commands = (  # type: ignore  # mypy doesn't like us overriding this.
        StatusV2,
        Announce,
        BlockHeaders, GetBlockHeaders,
        BlockBodies,
        Receipts,
        ProofsV2,
        ContractCodes,
    )
    cmd_length = 21

    def send_handshake(self, handshake_params: LESHandshakeParams) -> None:
        if handshake_params.version != self.version:
            raise ValidationError(
                f"LES protocol version mismatch: "
                f"params:{handshake_params.version} != proto:{self.version}"
            )
        resp = handshake_params.as_payload_dict()
        cmd = StatusV2(self.cmd_id_offset, self.snappy_support)
        self.logger.debug("Sending LES/Status msg: %s", resp)
        self.transport.send(*cmd.encode(resp))

    def send_get_proof(self,
                       block_hash: bytes,
                       account_key: bytes,
                       key: bytes,
                       from_level: int,
                       request_id: int=None) -> int:
        if request_id is None:
            request_id = gen_request_id()
        data = {
            'request_id': request_id,
            'proof_requests': [ProofRequest(block_hash, account_key, key, from_level)],
        }
        header, body = GetProofsV2(self.cmd_id_offset, self.snappy_support).encode(data)
        self.transport.send(header, body)

        return request_id


class ProxyLESProtocol:
    """
    An ``LESProtocol`` that can be used outside of the process that runs the peer pool. Any
    action performed on this class is delegated to the process that runs the peer pool.
    """
    def __init__(self,
                 session: SessionAPI,
                 event_bus: EndpointAPI,
                 broadcast_config: BroadcastConfig):
        self.session = session
        self._event_bus = event_bus
        self._broadcast_config = broadcast_config

    def send_handshake(self, handshake_params: LESHandshakeParams) -> None:
        raise NotImplementedError("API not implemented")

    def send_get_block_bodies(self, block_hashes: List[bytes], request_id: int=None) -> int:
        raise NotImplementedError("API not implemented")

    def send_get_block_headers(
            self,
            block_number_or_hash: Union[BlockNumber, Hash32],
            max_headers: int,
            skip: int,
            reverse: bool,
            request_id: int=None) -> int:
        raise NotImplementedError("API not implemented")

    def send_block_headers(self,
                           headers: Tuple[BlockHeader, ...],
                           buffer_value: int,
                           request_id: int=None) -> int:

        req_id = request_id if not None else gen_request_id()

        self._event_bus.broadcast_nowait(
            SendBlockHeadersEvent(self.session, headers, buffer_value, req_id),
            self._broadcast_config,
        )
        return req_id

    def send_get_receipts(self, block_hash: bytes, request_id: int=None) -> int:
        raise NotImplementedError("API not implemented")

    def send_get_proof(self, block_hash: bytes, account_key: bytes, key: bytes, from_level: int,
                       request_id: int=None) -> int:
        raise NotImplementedError("API not implemented")

    def send_get_contract_code(self, block_hash: bytes, key: bytes, request_id: int=None) -> int:
        raise NotImplementedError("API not implemented")
