"""Write a Korean report from the verified result matrix, without invented values."""
import argparse
import json
from pathlib import Path
import statistics


def write(root, output):
    data = json.loads((root / "comparison.json").read_text())
    verification = json.loads((root / "verification.json").read_text())
    nodes = [("nano", "Orin Nano"), ("agx", "AGX Orin"), ("spark", "DGX Spark")]
    models = sorted(json.loads((root / "models.json").read_text()), key=lambda m: m["size_bytes"])
    def label(m):
        return m["model"].replace(":", " ").replace("-instruct-q8_0", "").replace("llama3.2", "Llama 3.2").replace("qwen2.5", "Qwen 2.5").replace("gemma2", "Gemma 2")
    def metric(node, model, case, key, scale=1):
        row = next((r for r in data["conditions"] if r["node"] == node and r["model"] == model and r["case"] == case), None)
        if not row or row["blocks"] != 3 or row[key] is None:
            return "미완료"
        return f"{row[key]/scale:.3f}"
    verified = (verification["complete_cells"] == 54 and verification["successful_measured_requests"] == 972
        and verification["warmup_requests"] == 54
        and all(verification[k] for k in ["all_tokens_cache_valid", "all_unique_requests", "all_case_counts_valid", "all_physical_nodes_valid", "all_q8_verified",
            "all_gpu_verified", "all_cleanup_verified", "service_restored", "final_device_cleanup_verified",
            "final_pod_identity_preserved", "final_nodes_ready"])
        and all(verification["same_model_fixtures_match_all_devices_blocks"].values()))
    text = ["# 6개 모델 × Orin Nano·AGX Orin·DGX Spark 성능측정" + ("" if verified else " — 검증 미완료"), "", "## Material Passport", "",
        "- Material ID: multimodel-three-devices-20260910",
        "- Type: 실제 GPU 고정 토큰 추론 성능측정",
        "- Source: 사용자 지정 세 장비, 기존 Llama 1B 실험기, 요청별 JSONL과 GPU 실행 로그",
        "- Processing: 3회차 기술통계, 실제 토큰·캐시·GPU 적재·종료 검증",
        "- Verification: " + ("측정 및 원래 Llama 서비스 복구 검증 완료" if verified else "일부 미완료 — verification.json 확인 필요"), "",
        "## 무엇을 측정했나", "",
        "**같은 양의 글 조각을 읽고 쓰게 했을 때 각 모델과 장비가 얼마나 빨리 처리하는지 쟀다.** "
        "기존 Llama 1B와 함께 Llama 3B, Qwen 0.5B·1.5B·3B, Gemma 2B를 실제 세 장비에서 실행했다. "
        "RTX 대체값을 사용하지 않았다. 답변의 정답률이나 생산품질 모델 정확도 시험은 아니다.", "",
        "모든 모델은 Q8_0이며 llama-server d222767c7, context4096, slot1, thread4, batch512/128, "
        "f16 KV, flash attention off를 맞췄다. 실제 입력·출력 토큰과 요청 간 prefix 미재사용을 확인했다. "
        "모델 tokenizer가 달라 모델 사이의 문장/토큰 ID는 같지 않으며, 동일 모델의 장비별 입력은 일치한다.", "",
        "## 단일 요청의 응답시간", "",
        "**입력 512 → 출력 128토큰, 단위 초, 작을수록 빠르다.** 세 회차의 중앙값(n=3)이다. "
        "장비 내부 loopback HTTP 왕복을 포함하며 모델 적재·다운로드·냉각 대기는 제외한다.", "",
        "| 모델 (Q8_0) | Orin Nano | AGX Orin | DGX Spark |", "|---|---:|---:|---:|"]
    for m in models:
        text.append("| " + label(m) + " | " + " | ".join(metric(n, m["model"], "i512-o128-c1", "p50_latency_ms", 1000) for n, _ in nodes) + " |")
    hardware = {h["node"]: h for h in json.loads((root / "hardware.json").read_text())}
    pinned = json.loads((root / "nodes-before.json").read_text())
    text += ["", "## 장비와 실행 환경", "", "노드 메모리는 Kubernetes가 관측한 시스템 메모리다. "
        "컨테이너 제한, GPU 모델 할당량과 서로 다른 값이다. 기존 OS·CUDA backend·전력 설정을 유지했으므로 "
        "이 결과는 해당 설치 환경의 비교이며 장비별 최적 설정 탐색은 아니다.", "",
        "| 장비 | 관측 노드 메모리(GiB) | 런타임 컨테이너 메모리 제한 | OS | CUDA backend |",
        "|---|---:|---|---|---|"]
    for n, name in nodes:
        info = pinned[n]
        h = hardware[info["node"]]
        container = next(c for c in info["before"]["spec"]["containers"] if c["name"] == "inference-runtime")
        memory = int(h["capacity"]["memory"].removesuffix("Ki")) / 1024**2
        text.append(f"| {name} | {memory:.2f} | {container['resources']['limits']['memory']} | {h['nodeInfo']['osImage']} | {info['cuda']} |")
    text += ["", "## 8개가 동시에 도착했을 때", "", "단위 초, **대기를 포함한 n=24 표본 p95**다. "
        "slot1이므로 요청을 한 개씩 처리하고 나머지는 기다린다. 장시간 운영 p95나 동시에 8개를 계산한 결과가 아니다.", "",
        "| 모델 (Q8_0) | Orin Nano | AGX Orin | DGX Spark |", "|---|---:|---:|---:|"]
    for m in models:
        text.append("| " + label(m) + " | " + " | ".join(metric(n, m["model"], "i512-o128-c8", "p95_latency_ms", 1000) for n, _ in nodes) + " |")
    text += ["", f"![장비별 단일 요청 응답시간과 동시 8개 요청의 표본 p95 비교]({root.name}/model-comparison.png)",
        "", "## 처리량과 첫 토큰 지연", "", "기본 512/128 조건의 동시8 wave 세 번을 합친 결과다. "
        "출력 토큰/s는 성공 출력 토큰을 실제 wave 시간 합으로 나눈 값이며, "
        "개별 요청의 decode 속도나 장시간 지속 처리량과 다르다. TTFT는 처음 비어 있지 않은 응답을 받기까지다.", "",
        "| 장비 | 모델 | 출력 토큰/s | 요청/s | p95 TTFT(초) |", "|---|---|---:|---:|---:|"]
    for n, name in nodes:
        for m in models:
            text.append("| " + name + " | " + label(m) + " | " + " | ".join([
                metric(n, m["model"], "i512-o128-c8", "active_wave_output_tokens_s"),
                metric(n, m["model"], "i512-o128-c8", "active_wave_requests_s"),
                metric(n, m["model"], "i512-o128-c8", "p95_ttft_ms", 1000)]) + " |")
    text += ["", "## GPU 모델 적재량", "", "런타임 로그의 **GPU model buffer(MiB)**다. 모델 tensor용 할당량이며 "
        "KV/연산 buffer·드라이버·프로세스 RSS·장치 전체 메모리는 포함하지 않는다. 통합 메모리 장비의 전용 VRAM 측정값으로 부르지 않는다. "
        "JSON의 peak_process_rss_mib는 간헐적으로 관측한 RSS 중 최댓값이며, 조회 오류·샘플 사이의 실제 최고점을 보장하지 않는다.", "",
        "| 모델 | Orin Nano | AGX Orin | DGX Spark |", "|---|---:|---:|---:|"]
    for m in models:
        values = []
        for n, _ in nodes:
            buffers = [c.get("gpu_model_buffer_mib") for c in data["cells"] if c["node"] == n and c["model"] == m["model"] and c["complete"]]
            values.append(f"{statistics.median(buffers):.1f}" if len(buffers) == 3 and all(b is not None for b in buffers) else "미완료")
        text.append("| " + label(m) + " | " + " | ".join(values) + " |")
    text += ["", "## 실패 기록과 비교의 한계", "",
        f"- 최종 행렬: **{verification['complete_cells']}/54개 실행**, **{verification['successful_measured_requests']}/972개 요청 성공**. 준비 운동은 통계에서 제외했다.",
        "- 최초 a는 Spark Qwen 0.5B 18건 성공 후 시험기 포트 재사용 검사 오류로 중단됐다. "
        "해당 값은 최종 행렬에 섞지 않았다.",
        "- b의 Spark Llama 3B 첫 회차는 호스트 thermal zone 81.1°C로 80°C 중단 기준에 걸렸다. "
        "당시 GPU는 68°C였다. 중단 회차의 17개 측정 요청 중 15개 성공, 2개 실패/timeout, "
        "1개 미전송을 별도 보존했다. 25초 안의 초기 종료 확인은 실패했고, 후속 조회로 GPU 프로세스와 포트 부재를 확인했다.",
        "- Spark에서 완료되지 않은 13개 실행은 c에서 준비 운동/각 조건 전 모든 관측 thermal zone이 "
        "60°C 이하가 될 때까지 대기한 뒤 수행했다. 냉각 시간은 별도 cooling.jsonl에 있으며 응답시간·wave 처리량에서 제외했다. "
        "완료된 실행의 속도를 보고 좋은 결과만 고르지 않았다. 이 결과로 연속 고부하에서도 같은 속도가 유지된다고 주장할 수 없다.",
        "- Nano의 b/Qwen 3B에서는 관리 exec 연결이 중단됐다. 실제 GPU 프로세스는 남아 있었고 OOM 근거는 관측하지 못했다. "
        "9개 성공 terminal 기록, 진행 중 1개의 terminal 기록 유실, 아직 시작하지 않은 8개를 구분했다. 유실 요청의 지연시간을 추정하지 않았다.",
        "- Nano의 미완료 14개 실행은 d에서 장비 내부의 독립 timeout·프로세스·tmpfs 로그로 수행했다. "
        "각 조건 전 60°C 이하를 확인하며 관리 조회의 일시 오류만 재확인한다. 추론 요청 자체는 재시도하지 않는다. "
        "d의 첫 Qwen 3B 실행은 관리 측 조회가 중단됐지만 장비 내 18건이 모두 완료되어 원시 결과와 종료 상태를 회수했다. "
        "이 실행의 연속 자원 시계열에는 공백이 있으므로 프로세스 RSS의 최대치를 완전 계측했다고 주장하지 않는다.",
        "- b 실행기가 AGX 측정 후 서비스 복구를 기다리는 동안 Nano d가 다음 셀을 위해 서비스를 다시 일시정지해 "
        "b의 복구 대기는 timeout으로 끝났다. 복구 책임과 watchdog을 d에 넘겼으며 최종 상태는 모든 측정 후 "
        "별도 읽기 전용 감사로 확인한다. b 실행기의 exit code를 최종 측정 성공 여부로 대신하지 않는다.",
        "- 기동 기록은 관리 명령 시작→GPU health 관측의 복합 시간이다. Kubernetes exec 비용·polling 간격을 포함해 순수 모델 로딩 시간으로 해석하지 않는다.",
        "- 첫 회차는 크기 순, 이후 두 회차는 무작위 순서다. 같은 세션의 세 반복이며 독립 날짜 반복·holdout·장시간 지속 부하 검증은 없다.",
        "- 입력128/출력64, 입력2048/출력128, 입력512/출력256과 동시2/4 결과는 comparison.json/requests.csv에 포함된다.",
        "- 정답률, 모델의 지능, 시스템 에너지 절약, 자동 오프로딩 임계값, 장비별 최적 성능을 판정하지 않는다.", "",
        "## 원시 결과와 재현", "",
        f"- [조건별 전체 통계]({root.name}/comparison.json)",
        f"- [모델 파일·SHA256]({root.name}/models.json)",
        f"- [실제 노드 환경]({root.name}/hardware.json)",
        f"- [선택한 최종 행렬의 전체 요청 CSV]({root.name}/requests.csv)",
        f"- [검증 결과]({root.name}/verification.json)",
        f"- [중단 회차 요청]({root.name}/aborted-attempt-requests.json)",
        f"- [원래 서비스 복구]({root.name}/service-restored.json)",
        f"- [모든 실험 종료 후 최종 상태 확인]({root.name}/final-state.json)",
        f"- [그래프]({root.name}/model-comparison.png)", "",
        "[실험 계획](../다중모델-3장비-실험계획.md)과 저장소의 multimodel_*.py가 재현 코드다.", ""]
    output.write_text("\n".join(text))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    write(a.root, a.output)
