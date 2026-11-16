
from backend.agents.schemas import AgentConfig


class AgentRegistry:
    """
    Registro central para administrar los agentes de AGENT LAB.
    """

    def __init__(self):
        self._agents: dict[str, AgentConfig] = {}

    def register(self, agent: AgentConfig) -> AgentConfig:
        """
        Registra un agente nuevo.
        """

        if agent.id in self._agents:
            raise ValueError(f"Ya existe un agente con ID: {agent.id}")

        self._agents[agent.id] = agent
        return agent

    def get(self, agent_id: str) -> AgentConfig:
        """
        Busca un agente por su ID.
        """

        agent = self._agents.get(agent_id)

        if agent is None:
            raise KeyError(f"No se encontró el agente: {agent_id}")

        return agent

    def list_all(self) -> list[AgentConfig]:
        """
        Devuelve todos los agentes registrados.
        """

        return list(self._agents.values())

    def count(self) -> int:
        """
        Devuelve la cantidad de agentes registrados.
        """

        return len(self._agents)
