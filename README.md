## Installation

To install the project's dependencies, run this command:

```shell
pip install -r requirements.txt
```

## Configuration

Ensure you have valid API keys stored in `~/.streamlit/secrets.toml` (you only need them for the models you use):
```toml
OPENAI_API_KEY="sk-..."
ANTHROPIC_API_KEY="sk-ant-..."
CO_API_KEY="..."
```
Streamlit sets these as environment variables in `streamlit run`

## Running

The following command will run the app:
```shell
streamlit run Trilogue.py
```

The code in `Trilogue.py` will be reloaded when you refresh the page.
Streamlit's reloading behavior can be unintuitive in the following ways:
1. Other modules are not reloaded.
2. Persistent objects created using the old classes, etc. will continue
using those classes. These will use old versions of methods and fail
`isinstance` checks with the latest module's classes.

To avoid this, the application uses a single module.