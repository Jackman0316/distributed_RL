import sys
try:
    import selectors
except ImportError:
    import selectors2 as selectors
import io
import struct


class Message:
    def __init__(self, selector, sock, addr, request):
        self.selector = selector
        self.sock = sock
        self.addr = addr
        self.request = request
        self._recv_buffer = b""
        self._send_buffer = b""
        self._request_queued = False
        self.response = None
        self.content_length = None
        self.content_type = None

    def _set_selector_events_mask(self, mode):
        """Set selector to listen for events: mode is 'r', 'w', or 'rw'."""
        if mode == "r":
            events = selectors.EVENT_READ
        elif mode == "w":
            events = selectors.EVENT_WRITE
        elif mode == "rw":
            events = selectors.EVENT_READ | selectors.EVENT_WRITE
        else:
            raise ValueError("Invalid events mask mode %s." % (repr(mode)))
        self.selector.modify(self.sock, events, data=self)

    def _read(self):
        try:
            # Should be ready to read
            data = self.sock.recv(2048)
        except IOError:
            # Resource temporarily unavailable (errno EWOULDBLOCK)
            pass
        else:
            if data:
                self._recv_buffer += data
            else:
                raise RuntimeError("Peer closed.")

    def _write(self):
        if self._send_buffer:
            print("sending ", len(self._send_buffer),
                  "bytes of data to", self.addr)
            try:
                # Should be ready to write
                sent = self.sock.send(self._send_buffer)
            except IOError:
                # Resource temporarily unavailable (errno EWOULDBLOCK)
                pass
            else:
                self._send_buffer = self._send_buffer[sent:]

    def _create_message(
        self, content_bytes, content_type, content_encoding
    ):
        message_len_hdr = struct.pack(">L", len(content_bytes))
        message_type_hdr = struct.pack(">B", content_type)
        message = message_len_hdr + message_type_hdr + content_bytes
        return message

    def _process_response_binary_content(self):
        content = self.response
        # here maybe #TODO: receive new parameter data here
        print("got response: %s" % (repr(content)))

    def process_events(self, mask):
        if mask & selectors.EVENT_READ:
            parameters = self.read()
        if mask & selectors.EVENT_WRITE:
            self.write()
            parameters = None
        return parameters

    def read(self):
        self._read()

        self.process_protoheader()

        if self.content_length:
            while True:
                # print("Content Length:", self.content_length,
                #       "Recieve buffer len: ", len(self._recv_buffer))
                try:
                    self._read()
                except RuntimeError:
                    if (self.content_length >= len(self._recv_buffer)):
                        break
                    else:
                        raise RuntimeError
        return self.process_response()

    def write(self):
        if not self._request_queued:
            self.queue_request()

        self._write()

        if self._request_queued:
            if not self._send_buffer:
                # Set selector to listen for read events, we're done writing.
                self._set_selector_events_mask("r")

    def close(self):
        print("closing connection to", self.addr)
        try:
            self.selector.unregister(self.sock)
        except Exception as e:
            print(
                "error: selector.unregister() exception for %s: %s"
                % (self.addr, repr(e))
            )

        try:
            self.sock.close()
        except OSError as e:
            print(
                "error: socket.close() exception for %s: %s"
                % (self.addr, repr(e))
            )
        finally:
            # Delete reference to socket object for garbage collection
            self.sock = None

    def queue_request(self):
        content = self.request["content"]
        content_type = self.request["type"]
        content_encoding = self.request["encoding"]
        if content_type == "binary/pull":
            req = {
                "content_bytes": bytes([]),
                "content_type": 1,
                "content_encoding": content_encoding,
            }
        else:
            req = {
                "content_bytes": content,
                "content_type": 2,
                "content_encoding": content_encoding,
            }
        message = self._create_message(**req)
        self._send_buffer += message
        self._request_queued = True

    def process_protoheader(self):
        hdrlen = 5
        if len(self._recv_buffer) >= hdrlen:
            self.content_length = struct.unpack(
                ">L", self._recv_buffer[:4]
            )[0]
            self.content_type = struct.unpack(
                ">B", self._recv_buffer[4:5]
            )[0]
            self._recv_buffer = self._recv_buffer[hdrlen:]

    def process_response(self):
        content_len = self.content_length
        if not len(self._recv_buffer) >= content_len:
            return
        data = self._recv_buffer[:content_len]
        self._recv_buffer = self._recv_buffer[content_len:]
        parameters = None
        if self.content_type == 1:
            self.response = data
            print("received new parameters from ", self.addr)
            #print ("data: %s", data)
            parameters = data
        elif self.content_type == 3:
            # Binary or unknown content-type
            print("Ack Recieved: %s", data)
            self.response = data
        else:
            # Binary or unknown content-type
            print("Error, unknown type")
        # Close when response has been processed
        self.close()
        return parameters
