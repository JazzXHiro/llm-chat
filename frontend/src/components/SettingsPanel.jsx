// Values for the X-Simulate-Failure header (failover test hook on the backend)
const FAILURE_OPTIONS = [
  { value: '', label: 'Off (normal request)' },
  { value: 'key_1=429', label: 'key_1 = 429 (rate limit)' },
  { value: 'key_1=500', label: 'key_1 = 500 (server error)' },
  { value: 'key_1=429,key_2=500', label: 'key_1 = 429, key_2 = 500' },
  { value: '*=429', label: 'All keys = 429' },
]

// Side panel: optional system prompt for this session + failover test dropdown
export default function SettingsPanel({ systemPrompt, onSystemPromptChange, promptLocked, simulate, onSimulateChange }) {
  return (
    <aside className="settings">
      <label className="field">
        <span className="field-label">System prompt (optional)</span>
        <textarea
          data-testid="system-prompt-input"
          value={systemPrompt}
          onChange={(event) => onSystemPromptChange(event.target.value)}
          placeholder="e.g. You are a pirate. Answer in one sentence."
          rows={4}
          disabled={promptLocked}
        />
        <span className="field-hint">
          {promptLocked
            ? 'Locked for this session. Start a new chat to change it.'
            : 'Applies to this session. Leave empty to use the server default.'}
        </span>
      </label>

      <label className="field">
        <span className="field-label">Failover test</span>
        <select
          data-testid="simulate-failure-select"
          value={simulate}
          onChange={(event) => onSimulateChange(event.target.value)}
        >
          {FAILURE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="field-hint">
          Sends the <code>X-Simulate-Failure</code> header with each message (only honoured when
          the backend has <code>ENABLE_FAILURE_SIMULATION=true</code>).
        </span>
      </label>
    </aside>
  )
}
