(() => {
  const labs = document.querySelectorAll('[data-recovery-lab]');
  if (!labs.length) return;

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  labs.forEach((lab) => {
    const reset = lab.querySelector('[data-recovery-reset]');
    const cadence = lab.querySelector('[data-recovery-cadence]');
    const heartbeat = lab.querySelector('[data-recovery-heartbeat]');
    const play = lab.querySelector('[data-recovery-play]');
    const presetButtons = lab.querySelectorAll('[data-recovery-preset]');
    if (!reset || !cadence || !heartbeat || !play) return;

    const output = (selector) => lab.querySelector(selector);
    const resetLabel = output('[data-recovery-reset-label]');
    const cadenceOutput = output('[data-recovery-cadence-output]');
    const heartbeatOutput = output('[data-recovery-heartbeat-output]');
    const heartbeatTimeline = output('[data-recovery-heartbeat-timeline]');
    const firstData = output('[data-recovery-first-data]');
    const total = output('[data-recovery-total]');
    const experience = output('[data-recovery-experience]');
    const score = output('[data-recovery-score]');
    const status = output('[data-recovery-status]');
    const explain = output('[data-recovery-explain]');
    const stages = Array.from(lab.querySelectorAll('[data-recovery-stage]'));

    const values = () => {
      const hasReset = reset.checked;
      const cadenceMs = Number(cadence.value);
      const heartbeatMs = Number(heartbeat.value);
      const portReadyMs = 80;
      const firstDataMs = hasReset ? 1750 : cadenceMs;
      const enqueueMs = 1;
      const officialMs = portReadyMs + firstDataMs + enqueueMs;
      return { hasReset, cadenceMs, heartbeatMs, portReadyMs, firstDataMs, enqueueMs, officialMs };
    };

    const update = () => {
      const state = values();
      const pass = state.officialMs <= 400;
      const perceivedMs = state.heartbeatMs + state.officialMs;
      resetLabel.textContent = state.hasReset ? '켜짐' : '꺼짐';
      cadenceOutput.value = `${state.cadenceMs} ms`;
      heartbeatOutput.value = `${state.heartbeatMs} ms`;
      heartbeatTimeline.textContent = `${state.heartbeatMs} ms`;
      firstData.textContent = `${state.firstDataMs.toLocaleString('ko-KR')} ms`;
      total.value = `${state.officialMs.toLocaleString('ko-KR')} ms`;
      experience.value = `${perceivedMs.toLocaleString('ko-KR')} ms`;
      status.textContent = pass ? '통과 예상' : '초과 예상';
      score.textContent = pass ? '400 ms 내부 gate 통과 예상' : '400 ms 내부 gate 초과 예상';
      lab.classList.toggle('is-pass', pass);
      lab.classList.toggle('is-fail', !pass);
      explain.textContent = state.hasReset
        ? `아두이노가 다시 시작하면 약 1,750 ms를 기다려야 합니다. 전송 간격을 줄여도 400 ms 안에는 들어올 수 없습니다.`
        : state.cadenceMs > 300
          ? `자동 리셋은 막았지만 다음 쪽지가 최대 ${state.cadenceMs} ms 뒤에 옵니다. 센서 전송 주기도 400 ms 예산 안에 있어야 합니다.`
          : `자동 리셋을 막고 센서가 100 ms마다 쪽지를 보내면, port 준비와 EdgeX 전달까지 포함해 400 ms 안에 여유를 만들 수 있습니다.`;
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
      current: { reset: false, cadence: 100, heartbeat: 400 },
      reset: { reset: true, cadence: 100, heartbeat: 400 },
      slow: { reset: false, cadence: 1000, heartbeat: 400 },
    };

    [reset, cadence, heartbeat].forEach((control) => control.addEventListener('input', update));
    play.addEventListener('click', animate);
    presetButtons.forEach((button) => button.addEventListener('click', () => {
      const preset = presets[button.dataset.recoveryPreset];
      if (!preset) return;
      reset.checked = preset.reset;
      cadence.value = String(preset.cadence);
      heartbeat.value = String(preset.heartbeat);
      animate();
    }));

    update();
  });
})();
