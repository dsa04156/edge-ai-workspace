(() => {
  const labs = document.querySelectorAll('[data-recovery-lab]');
  if (!labs.length) return;

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  labs.forEach((lab) => {
    const reset = lab.querySelector('[data-recovery-reset]');
    const cadence = lab.querySelector('[data-recovery-cadence]');
    const request = lab.querySelector('[data-recovery-request]');
    const heartbeat = lab.querySelector('[data-recovery-heartbeat]');
    const play = lab.querySelector('[data-recovery-play]');
    const presetButtons = lab.querySelectorAll('[data-recovery-preset]');
    if (!reset || !cadence || !request || !heartbeat || !play) return;

    const output = (selector) => lab.querySelector(selector);
    const resetLabel = output('[data-recovery-reset-label]');
    const requestLabel = output('[data-recovery-request-label]');
    const cadenceOutput = output('[data-recovery-cadence-output]');
    const heartbeatOutput = output('[data-recovery-heartbeat-output]');
    const heartbeatTimeline = output('[data-recovery-heartbeat-timeline]');
    const firstData = output('[data-recovery-first-data]');
    const dataLabel = output('[data-recovery-data-label]');
    const total = output('[data-recovery-total]');
    const experience = output('[data-recovery-experience]');
    const score = output('[data-recovery-score]');
    const status = output('[data-recovery-status]');
    const explain = output('[data-recovery-explain]');
    const stages = Array.from(lab.querySelectorAll('[data-recovery-stage]'));

    const values = () => {
      const hasReset = reset.checked;
      const requestsNow = request.checked;
      const cadenceMs = Number(cadence.value);
      const heartbeatMs = Number(heartbeat.value);
      const portReadyMs = 125;
      const firstDataMs = hasReset ? 1750 : requestsNow ? 70 : cadenceMs;
      const enqueueMs = 5;
      const officialMs = portReadyMs + firstDataMs + enqueueMs;
      return { hasReset, requestsNow, cadenceMs, heartbeatMs, portReadyMs, firstDataMs, enqueueMs, officialMs };
    };

    const update = () => {
      const state = values();
      const pass = state.officialMs <= 400;
      const perceivedMs = state.heartbeatMs + state.officialMs;
      resetLabel.textContent = state.hasReset ? '켜짐' : '꺼짐';
      requestLabel.textContent = state.requestsNow ? '켜짐' : '꺼짐';
      cadenceOutput.value = `${state.cadenceMs} ms`;
      heartbeatOutput.value = `${state.heartbeatMs} ms`;
      heartbeatTimeline.textContent = `${state.heartbeatMs} ms`;
      firstData.textContent = `${state.firstDataMs.toLocaleString('ko-KR')} ms`;
      dataLabel.textContent = state.requestsNow ? '③ “지금 값” 요청·응답' : '③ 다음 쪽지를 기다림';
      total.value = `${state.officialMs.toLocaleString('ko-KR')} ms`;
      experience.value = `${perceivedMs.toLocaleString('ko-KR')} ms`;
      status.textContent = pass ? '통과 예상' : '초과 예상';
      score.textContent = pass ? '400 ms 내부 gate 통과 예상' : '400 ms 내부 gate 초과 예상';
      lab.classList.toggle('is-pass', pass);
      lab.classList.toggle('is-fail', !pass);
      explain.textContent = state.hasReset
        ? `아두이노가 다시 시작하면 약 1,750 ms를 기다려야 합니다. 전송 간격을 줄여도 400 ms 안에는 들어올 수 없습니다.`
        : state.requestsNow
          ? `평소에는 ${state.cadenceMs.toLocaleString('ko-KR')} ms마다 보냅니다. 재연결 뒤 첫 byte가 없을 때만 25 ms 간격으로 최대 네 번 묻고 답이 오면 멈추므로 계속 자주 보낼 필요가 없습니다.`
          : `즉시 요청이 없으면 다음 쪽지를 최대 ${state.cadenceMs.toLocaleString('ko-KR')} ms 기다립니다. 1초 주기에서는 400 ms를 보장할 수 없습니다.`;
      return state;
    };

    const animate = () => {
      update();
      stages.forEach((stage) => stage.classList.remove('is-active', 'is-complete'));
      lab.classList.remove('is-playing');
      void lab.offsetWidth;
      lab.classList.add('is-playing');
      const finish = () => {
        stages.forEach((stage) => stage.classList.add('is-complete'));
        lab.classList.remove('is-playing');
      };
      if (prefersReducedMotion) {
        finish();
        return;
      }
      stages.forEach((stage, index) => {
        window.setTimeout(() => {
          if (index > 0) stages[index - 1].classList.replace('is-active', 'is-complete');
          stage.classList.add('is-active');
          if (index === stages.length - 1) window.setTimeout(finish, 180);
        }, index * 180);
      });
    };

    const presets = {
      current: { reset: false, request: true, cadence: 1000, heartbeat: 400 },
      passive: { reset: false, request: false, cadence: 1000, heartbeat: 400 },
      reset: { reset: true, request: true, cadence: 1000, heartbeat: 400 },
    };

    [reset, request, cadence, heartbeat].forEach((control) => control.addEventListener('input', update));
    play.addEventListener('click', animate);
    presetButtons.forEach((button) => button.addEventListener('click', () => {
      const preset = presets[button.dataset.recoveryPreset];
      if (!preset) return;
      reset.checked = preset.reset;
      request.checked = preset.request;
      cadence.value = String(preset.cadence);
      heartbeat.value = String(preset.heartbeat);
      animate();
    }));

    update();
  });
})();
