"""Multicast transport for stomp.py.

Obviously not a typical message broker, but convenient if you don't have a broker, but still want to use stomp.py
methods.
"""

import websockets
import struct
import asyncio

from stomp.connect import BaseConnection
from stomp.protocol import *
from stomp.transport import *
from stomp.utils import *

MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5000


class WebSocketTransport(Transport):
    """
    Transport over multicast connections rather than using a broker.
    """
    def __init__(self):
        Transport.__init__(self, [], False, False, 0.0, 0.0, 0.0, 0.0, 0, False, None, None, None, None, False,
                           DEFAULT_SSL_VERSION, None, None, None)
        self.subscriptions = {}
        self.current_host_and_port = ('128.0.0.1', 8765)
        print('WebSocketTransport::__init__')
        
         
    async def connecting(self):
        websocket = await websockets.connect('ws://localhost:8765')
        return websocket
    async def disconnecting(self, websocket):
        await websocket.close()
        
            
    async def sending(self, websocket, msg):
        print("Sending< {}" .format(msg))
        await websocket.send(msg)
    
    async def receiving(self, websocket):
        rec_message = await websocket.recv()
        return rec_message
    
    def attempt_connection(self):
        """
        Establish a multicast connection - uses 2 sockets (one for sending, the other for receiving)
        """
        self.websocket = asyncio.get_event_loop().run_until_complete(self.connecting())
#          self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
# 
#         self.receiver_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
#         self.receiver_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#         self.receiver_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
#         self.receiver_socket.bind(('', MCAST_PORT))
#         mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
#         self.receiver_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print('WebSocketTransport::Attemp_Connection')
       

#         if not self.socket or not self.receiver_socket:
#             raise exception.ConnectFailedException()
    
    def send(self, encoded_frame):
        """
        Send an encoded frame through the mcast socket.

        :param bytes encoded_frame:
        """
        print('WebSocketTransport::Send')
#         self.socket.sendto(encoded_frame, (MCAST_GRP, MCAST_PORT))
        asyncio.get_event_loop().run_until_complete(self.sending(self.websocket, encoded_frame))
    
    
    
    def receive(self):
        """
        Receive 1024 bytes from the multicast receiver socket.

        :rtype: bytes
        """
        message = asyncio.get_event_loop().run_until_complete(self.receiving(self.websocket))
        return message

    def process_frame(self, f, frame_str):
        """
        :param Frame f: Frame object
        :param bytes frame_str: Raw frame content
        """
        frame_type = f.cmd.lower()

        if frame_type in ['disconnect']:
            return

        if frame_type == 'send':
            frame_type = 'message'
            f.cmd = 'MESSAGE'

        if frame_type in ['connected', 'message', 'receipt', 'error', 'heartbeat']:
            if frame_type == 'message':
                if f.headers['destination'] not in self.subscriptions.values():
                    return
                (f.headers, f.body) = self.notify('before_message', f.headers, f.body)
            self.notify(frame_type, f.headers, f.body)
        if 'receipt' in f.headers:
            receipt_frame = Frame('RECEIPT', {'receipt-id': f.headers['receipt']})
            lines = convert_frame_to_lines(receipt_frame)
            self.send(encode(pack(lines)))
        log.debug("Received frame: %r, headers=%r, body=%r", f.cmd, f.headers, f.body)
        print('WebSocketTransport::process_frame')
   
    def stop(self):
        print('WebSocketTransport::stop')
        
        Transport.stop(self)


class WebSocketConnection(BaseConnection, Protocol12):
    def __init__(self, wait_on_receipt=False):
        """
        :param bool wait_on_receipt: deprecated, ignored
        """
        print('WebSocketConnection::__init__')
        self.transport = WebSocketTransport()
        self.transport.set_listener('websocket-listener', self)
        self.transactions = {}
        Protocol12.__init__(self, self.transport, (0, 0))

    def connect(self, username=None, passcode=None, wait=False, headers=None, **keyword_headers):
        """
        :param str username:
        :param str passcode:
        :param bool wait:
        :param dict headers:
        :param keyword_headers:
        """
        self.transport.start()

    def subscribe(self, destination, id, ack='auto', headers=None, **keyword_headers):
        """
        :param str destination:
        :param str id:
        :param str ack:
        :param dict headers:
        :param keyword_headers:
        """
        print('WebSocketConnection::subscribe')
        self.transport.subscriptions[id] = destination

    def unsubscribe(self, id, headers=None, **keyword_headers):
        """
        :param str id:
        :param dict headers:
        :param keyword_headers:
        """
        print('WebSocketConnection::unsubscribe')
        del self.transport.subscriptions[id]

    def disconnect(self, receipt=None, headers=None, **keyword_headers):
        """
        :param str receipt:
        :param dict headers:
        :param keyword_headers:
        """
        print('WebSocketConnection::disconnect')
        Protocol12.disconnect(self, receipt, headers, **keyword_headers)
        self.transport.stop()

    def send_frame(self, cmd, headers=None, body=''):
        """
        :param str cmd:
        :param dict headers:
        :param body:
        """
        print('WebSocketConnection::send_frame')
        if headers is None:
            headers = {}
        frame = utils.Frame(cmd, headers, body)

        if cmd == CMD_BEGIN:
            trans = headers[HDR_TRANSACTION]
            if trans in self.transactions:
                self.notify('error', {}, 'Transaction %s already started' % trans)
            else:
                self.transactions[trans] = []
        elif cmd == CMD_COMMIT:
            trans = headers[HDR_TRANSACTION]
            if trans not in self.transactions:
                self.notify('error', {}, 'Transaction %s not started' % trans)
            else:
                for f in self.transactions[trans]:
                    self.transport.transmit(f)
                del self.transactions[trans]
        elif cmd == CMD_ABORT:
            trans = headers['transaction']
            del self.transactions[trans]
        else:
            if 'transaction' in headers:
                trans = headers['transaction']
                if trans not in self.transactions:
                    self.transport.notify('error', {}, 'Transaction %s not started' % trans)
                    return
                else:
                    self.transactions[trans].append(frame)
            else:
                self.transport.transmit(frame)
