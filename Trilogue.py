import dataclasses
import string
from enum import Enum

import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from streamlit.delta_generator import DeltaGenerator


class Character(str, Enum):
    USER = 'USER'
    CLAUDE_3_OPUS = 'CLAUDE_3_OPUS'
    GPT_4 = 'GPT_4'

    @classmethod
    def bots(cls) -> "list[Character]":
        return [Character.CLAUDE_3_OPUS, Character.GPT_4]

    @property
    def npc(self) -> bool:
        return self != 'USER'

    @property
    def model_slug(self) -> str:
        match self:
            case Character.CLAUDE_3_OPUS:
                return 'claude-3-opus-20240229'
            case Character.GPT_4:
                return 'gpt-4'
            case _:
                raise NotImplemented

    @property
    def display_name(self) -> str:
        match self:
            case Character.CLAUDE_3_OPUS:
                return 'Claude 3 Opus'
            case Character.GPT_4:
                return 'GPT-4'
            case _:
                raise NotImplementedError(self)

    def role_from_own_perspective(self, other: "Character") -> str:
        if self.npc ^ (self == other):
            return 'user'
        return 'assistant'


@dataclasses.dataclass
class Player:
    character: Character
    name: str
    index: int

    @property
    def display_name(self) -> str:
        return f"Player #{self.index} ({self.name})"

    def __repr__(self):
        return self.display_name


@dataclasses.dataclass
class Message:
    player: Player
    content: str

    def __post_init__(self):
        self.content = self.content.removeprefix(self.message_prefix).lstrip(string.punctuation)

    @property
    def message_prefix(self) -> str:
        return f'**{self.player.display_name}**'

    @property
    def llm_content(self) -> str:
        return self.message_prefix + '\n' + self.content

    def render(self, canvas: DeltaGenerator | None = None):
        if canvas is None:
            canvas = st.empty()
        with canvas.container():
            with st.chat_message("user" if self.player.character == Character.USER else "assistant"):
                st.markdown(self.message_prefix)
                st.markdown(self.content)


class OpenAIBackend:
    def __init__(self, client: OpenAI, system_prompt: str, self_: Player):
        self.client = client
        self.system_prompt = system_prompt
        self.self_ = self_

    def get_message_history(self, history: list[Message]) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        for m in history:
            messages.append({
                "role": self.self_.character.role_from_own_perspective(m.player.character),
                "content": m.llm_content
            })
        return messages

    def get_next_message(self, history: list[Message]) -> Message:
        resp = self.client.chat.completions.create(
            model=self.self_.character.model_slug,
            messages=self.get_message_history(history),
        )
        msg = resp.choices[0].message
        return Message(player=self.self_, content=msg.content)


class AnthropicBackend:
    def __init__(self, client: Anthropic, system_prompt: str, self_: Player):
        self.client = client
        self.system_prompt = system_prompt
        self.self_ = self_

    def get_message_history(self, history: list[Message]) -> list[dict]:
        messages = []
        for m in history:
            msg_ = {"role": self.self_.character.role_from_own_perspective(m.player.character),
                    "content": m.llm_content}
            try:
                if {messages[-1]['role'], msg_['role']} == {'user'}:
                    messages.append({"role": "assistant",
                                     "content": "<ignore>Token inserted by system for multi-player dialogue.</ignore>"})
            except IndexError:
                pass
            messages.append(msg_)
        return messages

    def get_next_message(self, history: list[Message]) -> Message:
        message = self.client.messages.create(
            model=self.self_.character.model_slug,
            messages=self.get_message_history(history),
            max_tokens=1024,
        )
        return Message(player=self.self_, content=message.content[0].text)


def create_backend(player: Player, system_prompt: str) -> AnthropicBackend | OpenAIBackend:
    match player.character:
        case Character.GPT_4:
            return OpenAIBackend(OpenAI(), system_prompt, player)
        case Character.CLAUDE_3_OPUS:
            return AnthropicBackend(Anthropic(), system_prompt, player)
        case _:
            raise NotImplementedError(player)


if 'messages' not in st.session_state:
    st.session_state.messages = []


def get_player_character():
    player1_name = st.text_input('Player #1', placeholder='User')
    if not player1_name:
        player1_name = 'User'
    return Player(character=Character.USER, name=player1_name, index=1)


def get_npc(*, index: int, default: Character):
    character = st.selectbox(f'Player #{index}', Character.bots(), index=Character.bots().index(default),
                             format_func=lambda x: x.display_name)
    return Player(character=character, name=character.display_name, index=index)


def get_system_prompt(current: Player, human: Player, opponent: Player) -> str:
    return f"""You are {current}. You are in a three-way conversation with a human user, {human}, and {opponent}, another AI, potentially another copy of yourself."""


player1 = get_player_character()
player2 = get_npc(index=2, default=Character.CLAUDE_3_OPUS)
player3 = get_npc(index=3, default=Character.GPT_4)
with st.expander("Advanced"):
    player2_prompt_default = get_system_prompt(player2, player1, player3)
    player2_prompt = st.text_area('Player #2 System Prompt', value=player2_prompt_default)
    player3_prompt_default = get_system_prompt(player3, player1, player2)
    player3_prompt = st.text_area('Player #3 System Prompt', value=player3_prompt_default)

for previous_message in st.session_state.messages:
    previous_message.render()

if prompt := st.chat_input():
    user_message = Message(player=player1, content=prompt)
    st.session_state.messages.append(user_message)
    user_message.render()
    player2_backend = create_backend(player2, player2_prompt)
    player2_message = player2_backend.get_next_message(st.session_state.messages)
    st.session_state.messages.append(player2_message)
    player2_message.render()
    player3_backend = create_backend(player3, player3_prompt)
    player3_message = player3_backend.get_next_message(st.session_state.messages)
    st.session_state.messages.append(player3_message)
    player3_message.render()
