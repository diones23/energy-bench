from yaml.parser import ParserError
from dotenv import load_dotenv
import argparse
import sys
import yaml
import os


from commands import BaseCommand
from languages import get_impl_cls
from prompts import build_energy_prompt
from spec import validate_data
from utils import *


class Generate(BaseCommand):
    name = "generate"
    help = "Generate and save new benchmark code using llms"

    def add_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--ollama", nargs="+", help="", default=[])
        parser.add_argument("--openai", nargs="+", help="", default=[])
        parser.add_argument("--deepseek", nargs="+", help="", default=[])
        parser.add_argument("--anthropic", nargs="+", help="", default=[])
        parser.add_argument(
            "files", nargs="+", type=argparse.FileType("r"), default=[sys.stdin], help=""
        )

    def handle(self, args: argparse.Namespace) -> None:
        load_dotenv()
        requested_models = {"ollama": [], "openai": [], "deepseek": [], "anthropic": []}
        requested_models["ollama"] = args.ollama
        requested_models["openai"] = args.openai
        requested_models["deepseek"] = args.deepseek
        requested_models["anthropic"] = args.anthropic

        for file in args.files:
            name = getattr(file, "name", "<stdin>")
            print_info(f"loading benchmark file '{name}'")

            try:
                data = yaml.safe_load(file)
            except ParserError as ex:
                raise ProgramError(f"failed while parsing benchmark data using {file} - {ex}")
            finally:
                if file is not sys.stdin:
                    file.close()

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

            for vendor, models in requested_models.items():
                if vendor == "ollama":
                    call_llm = self._with_ollama
                elif vendor == "openai":
                    call_llm = self._with_openai
                elif vendor == "deepseek":
                    call_llm = self._with_deepseek
                elif vendor == "anthropic":
                    call_llm = self._with_anthropic
                else:
                    call_llm = lambda m, c, t: ""

                for model in models:
                    print_info(f"generating code using {vendor} - {model}...")
                    code = call_llm(model, context, task)

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
            return response.response
        except (ollama.ResponseError, ConnectionError) as ex:
            raise ProgramError(f"failed while generating ollama reponse using model {model} - {ex}")

    def _with_openai(self, model: str, context: str, task: str) -> str:
        import openai

        try:
            response = openai.OpenAI().responses.create(
                model=model, instructions=context, input=task
            )
            return response.output_text
        except openai.APIConnectionError as ex:
            raise ProgramError(ex)
        except (openai.RateLimitError, openai.APIStatusError) as ex:
            raise ProgramError(ex)

    def _with_deepseek(self, model: str, context: str, task: str) -> str:
        import openai

        try:
            key = os.environ.get("DEEPSEEK_API_KEY")
            client = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
            response = openai.OpenAI().responses.create(
                model=model, instructions=context, input=task
            )
            response = (
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": context},
                        {"role": "user", "content": task},
                    ],
                )
                .choices[0]
                .message.content
            )
            return response if response else ""
        except openai.APIConnectionError as ex:
            raise ProgramError(ex)
        except (openai.RateLimitError, openai.APIStatusError) as ex:
            raise ProgramError(ex)

    def _with_anthropic(self, model: str, context: str, task: str) -> str:
        return ""
