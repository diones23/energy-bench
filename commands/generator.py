import yaml
import os

from languages import get_impl_cls
from prompts import build_energy_prompt
from spec import validate_data
from utils import *


class Generator:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir

    def generate_code(self, data: dict, ollama_model: str = "", openai_model: str = "") -> None:
        model = ""
        llm_func = lambda m, p, t: ""
        if ollama_model:
            model = ollama_model
            llm_func = self._with_ollama
            is_ollama = True
        else:
            is_ollama = False

        if openai_model:
            model = openai_model
            llm_func = self._with_openai
            is_openai = True
        else:
            is_openai = False

        if sum([is_ollama, is_openai]) > 1:
            raise ProgramError("multiple llm models passed")

        if not model:
            raise ProgramError("passing a model name is required")

        validated = validate_data(data)
        name = validated["name"]
        language = validated["language"]
        description = validated["description"]
        cls = get_impl_cls(language)

        if not cls:
            raise ProgramError(f"{language} is not a known implementation")
        if not description:
            raise ProgramError("benchmark doesn't have any description")

        try:
            imp = cls(**validated)
        except TypeError as ex:
            raise ProgramError(f"failed while initializing benchmark - {ex}")

        context, task = build_energy_prompt(imp)

        print_info("generating code...")
        code = llm_func(model, context, task)

        if code:
            generated_dir = os.path.join(self.base_dir, "generated", model, language)
            generated_file = os.path.join(generated_dir, f"{name}.yml")
            os.makedirs(generated_dir, exist_ok=True)

            validated["code"] = code

            try:
                with open(generated_file, "w") as file:
                    yaml.safe_dump(validated, file, indent=4, sort_keys=False)
            except IOError as ex:
                raise ProgramError(f"failed while writing to file - {ex}")

            print_success(f"Saved: {generated_file}")

    def _with_ollama(self, model: str, context: str, task: str) -> str:
        import ollama

        try:
            llm_available = False
            for _, ms in ollama.list():
                for m in ms:
                    if model == m.model:
                        llm_available |= True

            if not llm_available:
                raise ProgramError(f"{model} not available")

            response = ollama.generate(model=model, prompt=context + task)
        except (ollama.ResponseError, ConnectionError) as ex:
            raise ProgramError(f"failed while generating ollama reponse using model {model} - {ex}")
        return response.response

    def _with_openai(self, model: str, context: str, task: str) -> str:
        import openai

        try:
            response = openai.OpenAI().responses.create(
                model=model, instructions=context, input=task
            )
        except openai.APIConnectionError as ex:
            raise ProgramError(ex)
        except (openai.RateLimitError, openai.APIStatusError) as ex:
            raise ProgramError(ex)
        return response.output_text
