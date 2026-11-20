"""Measure the local Eureka/Feign Skill lab using only trusted fixture operations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from time import perf_counter, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REG = "http://127.0.0.1:18881"
FLOW = "http://127.0.0.1:18883"
EUREKA = "http://127.0.0.1:18761"
UID = "76d3bc58-1295-44b4-ac92-30295cac13c3"


def request(method, url, body=None, expected=200):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    start = perf_counter()
    try:
        with urlopen(req, timeout=15) as response:
            status, raw = response.status, response.read()
    except HTTPError as err:
        status, raw = err.code, err.read()
    if status != expected:
        raise RuntimeError(f"{method} {url} expected {expected}, got {status}: {raw[:250]!r}")
    return (json.loads(raw) if raw else None), (perf_counter() - start) * 1000


def append_skill(name, suffix):
    return f'---\nname: {name}\ndescription: Append a named marker to the input.\noperation: append\nsuffix: "{suffix}"\n---\nAppend the marker to the supplied text.\n'


def write_fixture(root, name, content):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(content, encoding="utf-8")
    (path / "skill.manifest.yaml").write_text("version: 1.0.0\ntype: text-transform\npermissions: []\ndependencies: []\n", encoding="utf-8")


def read_dataset_skill(source):
    with source.open(encoding="utf-8") as rows:
        row = next(item for item in map(json.loads, rows) if item["id"] == UID)
    original = row["skill_md"]
    body = re.sub(r"\A---\s*\n.*?^---\s*\n", "", original, count=1, flags=re.MULTILINE | re.DOTALL)
    document = (
        "---\nname: text-cleanup\ndescription: Remove a supported conversational opener from an input.\n"
        "operation: cleanup\n---\n"
        + body
    )
    return document, {
        "id": UID, "name": row["name"], "url": row.get("source_url"),
        "license_label": row.get("license"), "original_sha256": sha256(original.encode()).hexdigest(),
        "runtime_scope": "Deterministic implementation of selected opening filler rules and whitespace normalization.",
    }


def latency(values):
    values = sorted(values)
    return {f"p{p}_ms": round(values[min(len(values)-1, int(len(values)*p/100))], 2)
            for p in (50, 95, 99)}


def flow(names, text, expected):
    result, elapsed = request("POST", FLOW + "/flow", {"skills": names, "input": text})
    if result != {"skills": names, "output": expected}:
        raise AssertionError(f"Incorrect output for {names[:5]}")
    return elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stability-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.stability_seconds < 1:
        parser.error("--stability-seconds must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    source, source_meta = read_dataset_skill(args.dataset)
    names = ["text-cleanup"] + [f"marker-{n:02}" for n in range(1, 50)]
    docs = [source] + [append_skill(name, f"|{name}|") for name in names[1:]]
    for name, doc in zip(names, docs):
        write_fixture(args.output / "skills", name, doc)
    initial, _ = request("GET", REG + "/skills/stats")
    if initial["count"] != 0:
        raise SystemExit("Use a fresh lab registry with zero registrations.")
    discovery, _ = request("GET", EUREKA + "/eureka/apps")
    apps = {}
    for app in discovery["applications"]["application"]:
        instances = app["instance"]
        if isinstance(instances, dict):
            instances = [instances]
        apps[app["name"]] = [instance["status"] for instance in instances]
    assert all("UP" in apps.get(name, []) for name in ("SKILL-REGISTRY", "SKILL-WORKER", "SKILL-FLOW"))
    fixture_docs = [(args.output / "skills" / name / "SKILL.md").read_text(encoding="utf-8") for name in names]
    request("POST", REG + "/skills/batch", fixture_docs, 201)
    sample_ms = flow(["text-cleanup"], "Certainly!   Prepare the table.", "Prepare the table.")
    chain_output = "Example" + "".join(f"|{name}|" for name in names[1:])
    chain_ms = flow(names, "Certainly!  Example", chain_output)

    def serve(_):
        return flow(["text-cleanup", "marker-01"], "Great question!  Hello", "Hello|marker-01|")

    def churn(start):
        hot = append_skill("hot-probe", "|new|")
        elapsed = []
        for cycle in range(60):
            sleep(max(0, start + cycle * args.stability_seconds / 60 - perf_counter()))
            _, add_ms = request("POST", REG + "/skills/batch", [hot], 201)
            flow(["hot-probe"], "live", "live|new|")
            _, delete_ms = request("DELETE", REG + "/skills/hot-probe", expected=204)
            request("POST", FLOW + "/flow", {"skills": ["hot-probe"], "input": "live"}, 404)
            elapsed.append(add_ms + delete_ms)
        return elapsed

    def serve_until(deadline):
        results = []
        while perf_counter() < deadline:
            results.append(serve(None))
        return results

    concurrent_start = perf_counter()
    with ThreadPoolExecutor(max_workers=9) as pool:
        lifecycle = pool.submit(churn, concurrent_start)
        deadline = concurrent_start + args.stability_seconds
        workers = [pool.submit(serve_until, deadline) for _ in range(8)]
        calls = [elapsed for worker in workers for elapsed in worker.result()]
        churn_times = lifecycle.result()
    concurrent_seconds = perf_counter() - concurrent_start
    stable, _ = request("GET", REG + "/skills/stats")
    assert stable["count"] == 50 and stable["instance"] == initial["instance"]

    step_samples = []
    cap_start = perf_counter()
    current = 50
    while current < initial["capacity"]:
        count = min(1000, initial["capacity"] - current)
        batch = [append_skill(f"load-{i:06}", "|load|") for i in range(current, current+count)]
        result, elapsed = request("POST", REG + "/skills/batch", batch, 201)
        current += count
        assert result["count"] == current
        step_samples.append(elapsed)
    cap_seconds = perf_counter() - cap_start
    request("POST", REG + "/skills/batch", [append_skill("over-cap", "|overflow|")], 409)
    request("GET", REG + "/skills/over-cap", expected=404)
    capped, _ = request("GET", REG + "/skills/stats")
    assert capped["count"] == current and capped["instance"] == initial["instance"]
    cap_chain_ms = flow(names, "Certainly!  Example", chain_output)
    selected_load_skills = [f"load-{index:06}" for index in (50, (current + 50) // 2, current - 1)]
    flow(selected_load_skills, "Capacity check", "Capacity check|load||load||load|")
    with ThreadPoolExecutor(max_workers=8) as pool:
        capped_calls = list(pool.map(serve, range(1000)))
    for port in (18761, 18881, 18882, 18883):
        status, _ = request("GET", f"http://127.0.0.1:{port}/actuator/health")
        assert status["status"] == "UP"
    result = {
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_skill": source_meta, "eureka": apps,
        "smoke": {"registered": 50, "checked_chain_length": len(names),
                  "dataset_call_ms": round(sample_ms, 2), "chain_ms": round(chain_ms, 2)},
        "hot_reload": {"cycles": 60, "background_concurrency": 8, "successful_background_calls": len(calls), "errors": 0,
                       "expected_missing_404": 60, "duration_s": round(concurrent_seconds, 2),
                       "flow_latency": latency(calls), "add_plus_delete_latency": latency(churn_times)},
        "capacity": {"registered": current, "configured_limit": initial["capacity"],
                     "overflow_http": 409, "load_s": round(cap_seconds, 2), "batch_latency": latency(step_samples),
                     "chain_ms_at_limit": round(cap_chain_ms, 2), "successful_calls_at_limit": len(capped_calls),
                     "checked_capacity_fixture_skills": selected_load_skills,
                     "flow_latency_at_limit": latency(capped_calls)},
        "same_registry_instance": True, "final_health": "UP"
    }
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
