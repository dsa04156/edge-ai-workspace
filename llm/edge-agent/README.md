# KubeEdge Edge AI Operations Agent

Microsoft Agent Framework 기반의 KubeEdge Edge AI 운영 에이전트 플랫폼입니다. FastAPI 서비스로 동작하며 Local LLM은 OpenAI-compatible endpoint로 연결합니다.

## Architecture

```mermaid
flowchart TD
    U[Operator] --> API[FastAPI /chat]
    API --> C[Coordinator Agent]
    C --> S[Status Agent]
    C --> D[Device Agent]
    C --> M[Metrics Agent]
    C --> G[Diagnosis Agent]
    C --> P[Planner Agent]

    S --> K8S[Kubernetes API<br/>Node Pod Event GPU]
    D --> KE[KubeEdge CRD<br/>Device Device Twin]
    M --> PR[Prometheus]
    M --> MQ[MQTT Status]
    G --> C
    P --> AS[Approval Store<br/>pending_approval]

    API --> AP[POST /plans/{plan_id}/approve]
    AP --> AS

    C --> LLM[Local LLM<br/>OpenAI-compatible<br/>Qwen3 Gemma Llama]
```

## Why Microsoft Agent Framework

Microsoft Agent Framework를 사용하는 이유는 단순히 LLM에 tool 목록을 붙이는 구조보다 운영 역할을 명확히 나눌 수 있기 때문입니다. Coordinator, Status, Device, Metrics, Diagnosis, Planner를 독립 Agent로 구성하면 각 Agent의 instruction, tool 권한, 책임 범위를 분리할 수 있습니다.

단순 Tool Calling 구조는 하나의 모델 호출이 모든 도구를 직접 선택하고 실행하는 방식에 가깝습니다. 이 프로젝트는 Multi-Agent Workflow를 사용해 상태 조회, 장치 조회, 지표 분석, 원인 진단, 변경 계획 생성을 단계적으로 분리합니다. KubeEdge 운영 자동화에서는 Kubernetes 상태, EdgeCore/CloudCore 상태, Device Twin, RTSP AI 서비스 지연, GPU/Network 병목이 동시에 얽히므로 역할 분리가 중요합니다.

## Agent Responsibilities

- Coordinator Agent: 사용자 요청을 수신하고 Status, Metrics, Device, Diagnosis, Planner 결과를 종합합니다.
- Status Agent: Kubernetes Node, Pod, Event, GPU 상태를 읽기 전용으로 조회합니다.
- Device Agent: KubeEdge Device, Device Twin, Edge Device 상태를 조회합니다.
- Metrics Agent: Prometheus Query로 CPU, Memory, GPU, Network, RTT, Throughput 지표를 조회합니다.
- Diagnosis Agent: 장애 원인, 병목 원인, 서비스 상태를 진단합니다.
- Planner Agent: 오프로딩, 재배치, Scale-Out, Recovery Plan을 생성합니다. 절대 즉시 실행하지 않고 승인 대기 계획만 생성합니다.
- Executor Agent: 초기 버전에서는 구현하지 않습니다.

## Tool Design

운영용 tool은 범용 shell 실행 대신 제한된 읽기 전용 인터페이스로 구성합니다.

- `get_gpu_status(node_name: str | None = None) -> dict`
- `get_k8s_nodes() -> dict`
- `get_k8s_pods(namespace: str | None = None, label_selector: str | None = None) -> dict`
- `get_k8s_events(namespace: str | None = None) -> dict`
- `get_kubeedge_devices(namespace: str | None = None) -> dict`
- `get_device_twin(device_name: str, namespace: str) -> dict`
- `query_prometheus(query: str) -> dict`
- `get_mqtt_status() -> dict`

`run_shell(command: str)`은 테스트용이며 운영 전 제거/분리 필요합니다. 운영 전에는 반드시 `get_gpu_status`, `get_k8s_nodes`, `get_k8s_pods`, `query_prometheus` 같은 제한 tool로 분리해야 합니다. 코드와 instruction 모두에서 삭제, 재시작, 배포 변경, scale, rollout, apply, delete, patch, label, annotate 명령 실행을 금지합니다.

## Human-In-The-Loop Approval

`POST /chat`에서 Planner Agent가 필요한 요청으로 판단되면 즉시 실행하지 않고 승인 대기 상태의 plan을 저장합니다.

응답 형식:

```json
{
  "response": "...",
  "plan_id": "...",
  "approval_required": true
}
```

`POST /plans/{plan_id}/approve`는 계획 상태를 `approved_not_executed`로 변경합니다. 초기 버전에서는 승인 후에도 실제 `kubectl apply/delete/scale/rollout`을 실행하지 않습니다.

## Local LLM Configuration

```bash
export OPENAI_BASE_URL=http://<LLM_SERVER_IP>:11434/v1
export OPENAI_API_KEY=ollama
export OPENAI_MODEL_ID=qwen3:8b
export PROMETHEUS_URL=http://prometheus-kube-prometheus-prometheus.kube-system.svc:9090
```

Kubernetes 배포 기본값은 클러스터 내부 Ollama 서비스입니다.

```bash
kubectl apply -f ../ollama-qwen3.yaml
kubectl rollout status deployment/ollama-qwen3 --timeout=900s
export OPENAI_BASE_URL=http://ollama-qwen3.default.svc.cluster.local:11434/v1
```

## Run Locally

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Kubernetes Deployment

Agent Pod를 배치할 노드에 라벨을 지정합니다.

```bash
kubectl label node <server2-node-name> agent-node=true
```

이미지를 빌드합니다.

```bash
docker build -t 192.168.0.56:5000/edge-agent:latest .
docker push 192.168.0.56:5000/edge-agent:latest
```

단일 노드 또는 직접 import 방식:

```bash
docker save edge-agent:0.1 -o edge-agent-0.1.tar
# 대상 노드에서:
docker load -i edge-agent-0.1.tar
```

Registry 사용 방식:

```bash
docker tag edge-agent:0.1 <registry>/edge-agent:0.1
docker push <registry>/edge-agent:0.1
# edge-agent.yaml의 image를 <registry>/edge-agent:0.1로 변경
```

배포:

```bash
kubectl apply -f edge-agent.yaml
kubectl apply -f edge-agent-rbac.yaml
kubectl get pod -o wide
kubectl port-forward svc/edge-agent-svc 8000:8000
```

## API Test

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"공장 카메라 AI 서비스가 느린 이유 알려줘"}'
```

승인:

```bash
curl -X POST http://localhost:8000/plans/<plan_id>/approve
```

승인은 상태만 바꾸며 실제 운영 변경은 수행하지 않습니다.
