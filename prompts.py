from spec import Implementation


def build_energy_prompt(implementation: Implementation) -> tuple[str, str]:
    context = """# Context
You are an expert agent in generating programming code for doing energy measurements.
You will receive specific instructions to solve programming problems in any language.
Your objective is to create a reproducible solution by following the reproducibility protocol outlined below.
There are two loop structures depending on whether your solution requires initialization/cleanup:

1) With initialization and/or cleanup:
   loop do
       <initialization code: ensure the benchmark is in a consistent state>
       if start_rapl() == 0 then break
       <solution code>
       stop_rapl()
       <cleanup code>
   end

2) Without initialization or cleanup:
   while start_rapl() != 0
       <solution code>
       stop_rapl()
   end

## Notes:
- Only code between start_rapl() and stop_rapl() is measured
- Code outside that region is not measured
- start_rapl() internally reads an environment variable and returns the remaining iteration count
- The entire solution must be in a single file
- Use the simpler loop if initialization or cleanup are unnecessary
- DO NOT include any comments
- DO NOT print additional information (e.g., debug statements)
- Place the code within <code> and </code> tags. For example <code>print("Hello, world!")</code>"""

    task = """## Task
Name: {name}
Description: <<BEGIN DESCRIPTION>>{description}<<END DESCRIPTION>>
Language: {language}
Mandatory Dependencies: {dependencies}
Executable Command-Line Arguments: {args}

## Example usage of the reproducibility protocol for the {language} language: <<BEGIN RAPL USAGE>>{rapl_usage}<<END RAPL USAGE>>"""

    task = task.format(
        name=implementation.name,
        language=implementation.language,
        dependencies=",".join(implementation.dependencies),
        description=implementation.description,
        args=",".join(implementation.args),
        rapl_usage=implementation.rapl_usage,
    )
    return context, task
