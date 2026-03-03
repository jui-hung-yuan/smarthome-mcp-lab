"""AgentConfig: configuration dataclass for the local agent."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    memory_dir: Path = field(default_factory=lambda: Path.home() / ".smarthome" / "memory")

    # Directory containing skills/ subdirectories
    skills_dir: Path = field(
        default_factory=lambda: Path(__file__).parent / "skills"
    )

    # Claude model to use for the agent loop
    model: str = "claude-sonnet-4-6"

    # Maximum tokens per LLM response
    max_tokens: int = 4096

    # Use mock bulb instead of real hardware
    mock: bool = False

    # Path to mock bulb state file — shared with the MCP path (only used when mock=True)
    mock_state_file: Path = field(
        default_factory=lambda: Path.home() / ".smarthome" / "tapo_bulb_state.json"
    )

    # Ollama base URL for embeddings
    ollama_url: str = "http://localhost:11434"
