from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional, Union

from app.core.agent.types import AgentResponse, AgentStep
from app.core.llm.base import LLMProvider


class AgentPlugin(ABC):
    """
    Base class for agent plugins/tools.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Plugin description"""
        pass

    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """Return a list of tool definitions/functions"""
        pass


class Agent(ABC):
    """
    Abstract base class for Agents.
    """

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    @abstractmethod
    def run(
        self, input_text: str, context: Optional[Dict] = None
    ) -> Union[AgentResponse, Generator[AgentStep, None, None]]:
        """
        Run the agent on a given input.
        """
        pass
