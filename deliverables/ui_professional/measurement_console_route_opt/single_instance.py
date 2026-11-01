"""Reuse this instrument window; opening its shortcut never reprograms FPGA."""
from pathlib import Path
import atexit, json, os, queue, secrets, socket, socketserver, threading

def show_existing(runtime):
    endpoint=Path(runtime)/'gui_endpoint.json'
    try:
        info=json.loads(endpoint.read_text(encoding='utf-8'))
        with socket.create_connection(('127.0.0.1',int(info['port'])),timeout=1) as connection:
            connection.settimeout(1)
            connection.sendall((json.dumps(dict(op='show',token=info['token']))+'\n').encode())
            return json.loads(connection.makefile('r').readline(1024)).get('accepted') is True
    except (OSError,ValueError,KeyError):return False

def install(app,runtime):
    runtime=Path(runtime);runtime.mkdir(exist_ok=True)
    # The original msvcrt byte lock fails on some Windows/D: installations even when no UI is running.
    # The endpoint check above remains the single-instance guard.
    lease=None
    messages=queue.Queue();token=secrets.token_hex(24)
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                self.connection.settimeout(2)
                request=json.loads(self.rfile.readline(1024))
                accepted=request.get('token')==token and request.get('op')=='show'
                if accepted:messages.put('show')
                self.wfile.write((json.dumps(dict(accepted=accepted))+'\n').encode())
            except (OSError,ValueError):pass
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads=True
    server=Server(('127.0.0.1',0),Handler)
    endpoint=runtime/'gui_endpoint.json'
    endpoint.write_text(json.dumps(dict(pid=os.getpid(),port=server.server_address[1],token=token)),encoding='utf-8')
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def poll():
        show=False
        while True:
            try:messages.get_nowait();show=True
            except queue.Empty:break
        if show:app.deiconify();app.lift();app.focus_force()
        app.after(100,poll)
    app.after(100,poll)
    closed=False
    def cleanup():
        nonlocal closed
        if closed:return
        closed=True
        server.shutdown()
        server.server_close()
        try:
            if json.loads(endpoint.read_text())['token']==token:endpoint.unlink()
        except (OSError,ValueError,KeyError):pass
        if lease: lease.close()
    atexit.register(cleanup)
    return cleanup


