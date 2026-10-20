"""Local RouteMind workspace. Standard-library HTTP server and native NS-3 jobs."""
import argparse
import copy
import csv
from datetime import datetime, timezone
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import unquote, urlsplit
import uuid
import webbrowser

from build import ROOT, environment, load_runtime
from run_matrix import source_hashes
from scenario_config import DEFAULT, MODES, SCENARIOS, template, validate, write_network

RUNS = ROOT / "results/gui"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")
    temp.replace(path)


class Jobs:
    def __init__(self):
        RUNS.mkdir(parents=True,exist_ok=True)
        self.lock = threading.Lock()
        self.active = None
        self.process = None
        self.cancel = threading.Event()
        self.records = {}
        for path in RUNS.glob("*/run.json"):
            try:
                record = read_json(path)
                if record["status"] in {"running","verifying","queued"}:
                    record.update(status="interrupted",error="Server stopped before this run completed")
                    write_json(path,record)
                self.records[record["id"]] = record
            except (ValueError,KeyError,OSError):
                continue

    def save(self, record):
        write_json(RUNS / record["id"] / "run.json",record)

    def start(self, raw, compare):
        config = validate(raw)
        if type(compare) is not bool:
            raise ValueError("compare must be true or false")
        if compare and config["scenario"] == "calibration":
            raise ValueError("Calibration runs in static mode; comparison is unavailable")
        runtime = load_runtime()
        with self.lock:
            if self.active:
                raise ValueError("An experiment is already running. Stop it or wait for completion.")
            identifier = datetime.now().strftime("%Y%m%d-%H%M%S-")+uuid.uuid4().hex[:6]
            record = {"id":identifier,"name":config["name"],"created":datetime.now(timezone.utc).isoformat(),
                      "status":"queued","config":config,"compare":compare,"cases":[],"error":None}
            (RUNS / identifier).mkdir()
            self.records[identifier] = record
            self.active = identifier
            self.cancel.clear()
            self.save(record)
            threading.Thread(target=self.worker,args=(record,runtime),daemon=True).start()
            return copy.deepcopy(record)

    def command(self, command, logfile):
        with logfile.open("w",encoding="utf-8") as stream:
            with self.lock:
                if self.cancel.is_set():
                    raise RuntimeError("Cancelled by user")
                self.process = subprocess.Popen(command,cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT)
                process = self.process
            code = process.wait()
            with self.lock:
                self.process = None
            if self.cancel.is_set():
                raise RuntimeError("Cancelled by user")
            if code:
                raise RuntimeError(logfile.read_text(encoding="utf-8",errors="replace")[-1800:] or f"Process exited with {code}")

    def worker(self, record, runtime):
        root = RUNS / record["id"]
        config = record["config"]
        modes = MODES if record["compare"] else [config["mode"]]
        parameters = {key:config[key] for key in ["duration","interval","alpha","dwell","threshold","policy"]}
        parameters.update({"topology":config["topology"],"pcap":int(config["pcap"]),
                           "loop-safe":int(config["loop_safe"]),"audit-forwarding":int(config["audit"])})
        if config["scenario"] == "calibration":
            parameters["calibration-rate-mbps"] = config["calibration_rate"]
        if config["custom"]:
            write_network(config,root / "network.txt")
            parameters["network-file"] = str(root / "network.txt")
        matrix = {"seed":config["seed"],"runs":[config["run"]],"scenarios":[config["scenario"]],
                  "modes":modes,"parameters":parameters}
        write_json(root / "scenario.json",config)
        manifest = {"config":matrix,"runtime":runtime,"source_sha256":source_hashes(),"status":"running","completed":[],
                    "executable_sha256":runtime["executable_sha256"],
                    "scenario_sha256":hashlib.sha256((root / "scenario.json").read_bytes()).hexdigest()}
        if config["custom"]:
            manifest["network_sha256"] = hashlib.sha256((root / "network.txt").read_bytes()).hexdigest()
        write_json(root / "manifest.json",manifest)
        try:
            for mode in modes:
                case = f"{config['scenario']}-run{config['run']}-{mode}"
                target = root / case
                target.mkdir()
                record.update(status="running",current_case=case)
                self.save(record)
                command = [runtime["executable"],f"--mode={mode}",f"--scenario={config['scenario']}",
                           f"--seed={config['seed']}",f"--run={config['run']}",f"--output={target}"]
                command += [f"--{key}={value}" for key,value in parameters.items()]
                self.command(command,target / "console.log")
                record["status"] = "verifying"
                self.save(record)
                self.command([sys.executable,str(ROOT / "tests/verify_results.py"),str(target)],target / "verification.log")
                record["cases"].append(case)
                manifest["completed"].append(case)
                self.save(record)
                write_json(root / "manifest.json",manifest)
            if load_runtime() != runtime:
                raise RuntimeError("Build changed during experiment")
            manifest["status"] = "complete"
            write_json(root / "manifest.json",manifest)
            self.command([sys.executable,str(ROOT / "analysis/report.py"),str(root)],root / "report.log")
            record["status"] = "complete"
        except (Exception, SystemExit) as error:
            record.update(status="cancelled" if self.cancel.is_set() else "failed",error=str(error))
            manifest["status"] = record["status"]
            write_json(root / "manifest.json",manifest)
        finally:
            self.save(record)
            with self.lock:
                self.active = None

    def stop(self, identifier):
        with self.lock:
            if self.active != identifier:
                raise ValueError("This experiment is not running")
            self.cancel.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def snapshot(self, identifier):
        if identifier not in self.records:
            raise ValueError("Experiment not found")
        result = copy.deepcopy(self.records[identifier])
        result["summaries"] = []
        root = RUNS / identifier
        for case in result["cases"]:
            result["summaries"].append({"case":case,**read_json(root / case / "summary.json")})
        result["progress"] = 0
        if result.get("current_case"):
            path = root / result["current_case"] / "progress.csv"
            try:
                data = path.read_text().splitlines()[-1].split(",")
                result["progress"] = float(data[0])
            except (OSError,ValueError,IndexError):
                pass
        return result


def csv_rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self,value,status=200):
        data = json.dumps(value,allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}",f"localhost:{port}"}
        return self.headers.get("Host") in allowed and (not self.headers.get("Origin") or
            self.headers.get("Origin") in {f"http://{host}" for host in allowed})

    def do_GET(self):
        if not self.allowed():
            self.send_error(403)
            return
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/bootstrap":
                try:
                    runtime = load_runtime()
                    backend = {"ready":True,"version":runtime["ns3_version"]}
                except SystemExit as error:
                    backend = {"ready":False,"error":str(error)}
                self.send_json({"default":DEFAULT,"templates":{name:template(name) for name in ["parallel","extended","detour"]},
                                "modes":MODES,"scenarios":SCENARIOS,"backend":backend})
                return
            if path == "/api/jobs":
                self.send_json([self.server.jobs.snapshot(key) for key in sorted(self.server.jobs.records,reverse=True)])
                return
            match = re.fullmatch(r"/api/jobs/([\w-]+)(?:/(data|files)(?:/(.*))?)?",path)
            if match:
                identifier, action, filename = match.groups()
                job = self.server.jobs.snapshot(identifier)
                if not action:
                    self.send_json(job)
                elif action == "data":
                    summaries = job["summaries"]
                    if not summaries:
                        raise ValueError("No verified case is available yet")
                    query = urlsplit(self.path).query
                    selected = next((item for item in summaries if item["mode"] == query.removeprefix("mode=")),summaries[0])
                    case = RUNS / identifier / selected["case"]
                    packets = csv_rows(case / "realtime-packets.csv")
                    bins = {}
                    for row in packets:
                        key = int(float(row["time"])*2)/2
                        bins.setdefault(key,[]).append(float(row["delay_ms"]))
                    self.send_json({"summary":selected,"topology":read_json(case / "topology.json"),
                        "routes":csv_rows(case / "routes.csv"),"telemetry":csv_rows(case / "telemetry.csv"),
                        "events":csv_rows(case / "events.csv"),"decisions":csv_rows(case / "decisions.csv"),
                        "delay_series":[{"time":stamp,"delay":sum(values)/len(values),"received":len(values)} for stamp,values in sorted(bins.items())],
                        "artifacts":[file.name for file in sorted(case.iterdir()) if file.is_file()]})
                else:
                    root = (RUNS / identifier).resolve()
                    target = (root / (filename or "scenario.json")).resolve()
                    if not target.is_relative_to(root) or not target.is_file() or target.suffix not in {".json",".csv",".log",".xml",".pcap",".md",".txt"}:
                        raise ValueError("Artifact not found")
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type",mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                    self.send_header("Content-Disposition",f'attachment; filename="{target.name}"')
                    self.send_header("Content-Length",str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                return
            if path not in {"/","/index.html","/app.js","/style.css"}:
                self.send_error(404)
                return
            super().do_GET()
        except (ValueError,OSError,KeyError) as error:
            self.send_json({"error":str(error)},400)

    def do_POST(self):
        if not self.allowed() or self.headers.get_content_type() != "application/json":
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length","0"))
            if not 0 < size <= 65536:
                raise ValueError("Invalid request size")
            value = json.loads(self.rfile.read(size))
            if self.path == "/api/jobs":
                self.send_json(self.server.jobs.start(value["config"],value.get("compare",False)),201)
            elif self.path == "/api/validate":
                self.send_json(validate(value))
            elif re.fullmatch(r"/api/jobs/[\w-]+/stop",self.path):
                self.server.jobs.stop(self.path.split("/")[3])
                self.send_json({"ok":True})
            else:
                self.send_error(404)
        except (ValueError,KeyError,TypeError,SystemExit) as error:
            self.send_json({"error":str(error)},400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--no-browser",action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1",args.port),partial(Handler,directory=str(ROOT / "web")))
    server.jobs = Jobs()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"RouteMind workspace: {url}\nKeep this terminal open. Press Ctrl+C to stop.",flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if server.jobs.active:
            server.jobs.stop(server.jobs.active)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
