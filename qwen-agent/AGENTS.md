# Qwen vLLM Compose — Agent Instructions

루트 `../AGENTS.md`를 먼저 적용한다. 이 디렉터리는 NVIDIA GPU 한 대에서 Qwen vLLM
OpenAI-compatible endpoint를 띄우는 독립 local Compose 설정이다. 현재 EdgeX/KubeEdge
운영 plane이나 agent-assisted 전역 제어 기능이 아니다.

## Run & Validate

```bash
docker compose config
docker compose up -d qwen-vllm
docker compose logs -f qwen-vllm
docker compose down
```

첫 실행은 큰 model image/weight를 내려받고 모든 GPU를 예약한다. 실행 전에 대상 host의
GPU 여유, cache 용량과 port 8000 충돌을 확인한다.

## Structure

- `docker-compose.yml` — vLLM image, Qwen model, GPU와 serving parameter

## Boundaries

- ✅ **Always do:** `docker compose config`로 syntax와 resolved 설정을 확인한다.
- ⚠️ **Ask first:** model, image tag, quantization, context length, GPU memory, port 또는 host cache mount를 변경한다.
- 🚫 **Never do:** endpoint를 인증 없이 외부에 노출하거나 이 모델이 현재 플랫폼을 자율 제어한다고 설명한다.
