import dataclasses
from enum import Enum
from typing import Iterable

import cohere
import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from streamlit.delta_generator import DeltaGenerator


class Character(str, Enum):
    USER = 'USER'
    CLAUDE_3_OPUS = 'CLAUDE_3_OPUS'
    GPT_4 = 'GPT_4'
    GPT_35 = 'GPT_35'
    COMMAND_R_PLUS = 'COMMAND_R_PLUS'
    COMMAND_R = 'COMMAND_R'

    @classmethod
    def bots(cls) -> "list[Character]":
        return [Character.CLAUDE_3_OPUS, Character.COMMAND_R_PLUS, Character.COMMAND_R, Character.GPT_4,
                Character.GPT_35]

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
            case Character.GPT_35:
                return 'gpt-3.5-turbo'
            case Character.COMMAND_R_PLUS:
                return 'command-r-plus'
            case Character.COMMAND_R:
                return 'command-r'
            case _:
                raise NotImplemented

    @property
    def display_name(self) -> str:
        match self:
            case Character.CLAUDE_3_OPUS:
                return 'Claude 3 Opus'
            case Character.GPT_4:
                return 'GPT-4'
            case Character.GPT_35:
                return 'GPT-3.5'
            case Character.COMMAND_R_PLUS:
                return 'Command R+'
            case Character.COMMAND_R:
                return 'Command R'
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
    content: str | Iterable[str]

    def _clean_iterable(self, content: Iterable[str]) -> Iterable[str]:
        continue_ = True
        it = iter(content)
        prefix = self.message_prefix
        try:
            while continue_:
                chunk = next(it)
                clean = self._clean_content(chunk, prefix)
                chopped_len = len(chunk) - len(clean)
                prefix = prefix[chopped_len:]
                if clean:
                    yield clean
                    continue_ = False
            yield from it
        except StopIteration:
            return

    def _clean_content(self, content: str, prefix: str | None = None) -> str:
        if prefix is None:
            prefix = self.message_prefix
        prefix = prefix[:len(content)]
        return content.removeprefix(prefix)

    def _ensure_clean_content_iterable(self) -> Iterable[str]:
        content = self.content
        if isinstance(content, str):
            yield self._clean_content(content)
        else:
            parts = []
            for chunk in self._clean_iterable(content):
                parts.append(chunk)
                yield chunk
            self.content = "".join(parts)

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
                st.write_stream(self._ensure_clean_content_iterable())


class OpenAIBackend:
    def __init__(self, client: OpenAI, system_prompt: str, self_: Player):
        self.client = client
        self.system_prompt = system_prompt
        self.self_ = self_

    def get_message_history(self, history: list[Message]) -> list[dict]:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system",
             "content": "Do not include a name in your message. Names will be included by the system."},
        ]
        for m in history:
            if not isinstance(m.content, str):
                break
            messages.append({
                "role": self.self_.character.role_from_own_perspective(m.player.character),
                "content": m.llm_content
            })
        return messages

    def get_next_message(self, history: list[Message]) -> Message:
        content = self._get_content_stream(history)
        return Message(player=self.self_, content=content)

    def _get_content_stream(self, history: list[Message]) -> Iterable[str]:
        resp = self.client.chat.completions.create(
            model=self.self_.character.model_slug,
            messages=self.get_message_history(history),
            stream=True,
            temperature=temperature,
            top_p=top_p,
        )
        for chunk in resp:
            chunk_content = chunk.choices[0].delta.content
            if chunk_content:
                yield chunk_content


class AnthropicBackend:
    def __init__(self, client: Anthropic, system_prompt: str, self_: Player):
        self.client = client
        self.system_prompt = system_prompt
        self.self_ = self_

    def get_message_history(self, history: list[Message]) -> list[dict]:
        messages = []
        for m in history:
            if not isinstance(m.content, str):
                break
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
        content = self._get_content_stream(history)
        return Message(player=self.self_, content=content)

    def _get_content_stream(self, history: list[Message]) -> Iterable[str]:
        with self.client.messages.stream(
                model=self.self_.character.model_slug,
                messages=self.get_message_history(history),
                max_tokens=1024,
                temperature=temperature,
                top_p=top_p,
        ) as stream:
            yield from stream.text_stream


class CohereBackend:
    def __init__(self, client: cohere.Client, system_prompt: str, player: Player):
        self.client = client
        self.system_prompt = system_prompt
        self.player = player

    def _convert_role(self, role: str) -> str:
        return {'user': 'USER', 'assistant': 'CHATBOT', 'system': 'SYSTEM'}[role]

    def _convert_message(self, m: Message) -> dict:
        return {
            'role': self._convert_role(self.player.character.role_from_own_perspective(m.player.character)),
            'message': m.llm_content,
        }

    def get_next_message(self, history: list[Message]) -> Message:
        system = {'role': 'SYSTEM', 'message': self.system_prompt}
        encoded = [self._convert_message(m) for m in history]
        response = self.client.chat(
            model=self.player.character.model_slug,
            chat_history=[system, *encoded[:-1]],
            message=encoded[-1]['message'],
            connectors=[{'id': 'web-search'}]
        )
        return Message(player=self.player, content=response.text)


def create_backend(player: Player, system_prompt: str) -> AnthropicBackend | OpenAIBackend | CohereBackend:
    match player.character:
        case Character.GPT_4 | Character.GPT_35:
            return OpenAIBackend(OpenAI(), system_prompt, player)
        case Character.CLAUDE_3_OPUS:
            return AnthropicBackend(Anthropic(), system_prompt, player)
        case Character.COMMAND_R | Character.COMMAND_R_PLUS:
            return CohereBackend(cohere.Client(), system_prompt, player)
        case _:
            raise NotImplementedError(player)


if 'messages' not in st.session_state:
    st.session_state.messages = []


def get_player_character():
    player1_name = st.text_input('Player #1', placeholder='Mira')
    if not player1_name:
        player1_name = 'User'
    return Player(character=Character.USER, name=player1_name, index=1)


def get_npc(*, index: int, default: Character):
    character = st.selectbox(f'Player #{index}', Character.bots(), index=Character.bots().index(default),
                             format_func=lambda x: x.display_name)
    return Player(character=character, name=character.display_name, index=index)


def get_system_prompt(current: Player, human: Player, opponent: Player) -> str:
    return f"""You are {current}. You are in a three-way conversation with a human user, {human}, and {opponent}, another AI, potentially another copy of yourself."""


with st.sidebar:
    player1 = get_player_character()
    player2 = get_npc(index=2, default=Character.CLAUDE_3_OPUS)
    player3 = get_npc(index=3, default=Character.COMMAND_R_PLUS)
    if st.button(label='Clear History 🔄'):
        st.session_state.messages = []
    with st.expander("Advanced"):
        player2_prompt_default = get_system_prompt(player2, player1, player3)
        player2_prompt = st.text_area('Player #2 System Prompt', value=player2_prompt_default)
        player3_prompt_default = get_system_prompt(player3, player1, player2)
        player3_prompt = st.text_area('Player #3 System Prompt', value=player3_prompt_default)
        top_p = st.slider(label='Top-p', min_value=0.0, max_value=1.0, value=1.0)
        temperature = st.slider(label='Temperature', min_value=0.0, max_value=1.0, value=1.0)

for previous_message in st.session_state.messages:
    previous_message.render()

if prompt := st.chat_input():
    user_message = Message(player=player1, content=prompt)
    st.session_state.messages.append(user_message)
    user_message.render()
    player2_backend = create_backend(player2, player2_prompt)
    player2_message = player2_backend.get_next_message(st.session_state.messages)
    player2_message.render()
    st.session_state.messages.append(player2_message)
    player3_backend = create_backend(player3, player3_prompt)
    player3_message = player3_backend.get_next_message(st.session_state.messages)
    player3_message.render()
    st.session_state.messages.append(player3_message)
