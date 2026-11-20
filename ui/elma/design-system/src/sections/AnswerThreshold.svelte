<script lang="ts">
  const id = $props.id();
</script>

<div class="answer-threshold" role="separator" aria-label="Final answer starts here">
  <svg viewBox="0 0 720 180" preserveAspectRatio="xMidYMid slice" fill="none" aria-hidden="true">
    <defs>
      <radialGradient id={id}>
        <stop stop-color="currentColor" stop-opacity=".32" />
        <stop offset="1" stop-color="currentColor" stop-opacity="0" />
      </radialGradient>
    </defs>
    <path class="mist" d="M0 124C112 101 185 130 278 111c81-17 142-12 207 1 94 20 148-15 235-2v70H0Z" />
    <circle cx="360" cy="112" r="72" fill={'url(#' + id + ')'} />
    <path class="hair" d="M0 128c97-4 173 1 260-5 44-3 70-22 100-22s55 19 100 22c87 6 163 1 260 5" />
    <path class="strong" d="M309 122a51 51 0 0 1 102 0" />
    <path class="ray" d="M360 51V18M316 64l-21-29M404 64l21-29M282 92l-36-15M438 92l36-15" />
  </svg>
</div>

<style>
  .answer-threshold {
    height: clamp(76px, 14vw, 112px);
    color: var(--accent);
  }
  svg { display: block; width: 100%; height: 100%; overflow: hidden; }
  .mist { fill: color-mix(in srgb, currentColor 8%, transparent); }
  .hair, .strong, .ray { stroke: currentColor; stroke-linecap: round; }
  .hair { stroke-width: 1.3; opacity: .42; }
  .strong { stroke-width: 2; }
  .ray { stroke-width: 1.2; opacity: .58; }
</style>
