## Installation

To install the project's dependencies, run this command:

```shell
pip install -r requirements.txt
```

## Running

The following command will run the app:
```shell
streamlit run Trilogue.py
```

The code in `Trilogue.py` will be reloaded when you refresh the page.
This behavior can be unintuitive in the following ways:
1. Other modules are not reloaded.
2. Persistent objects created using the old classes, etc. will continue
using those classes. This can fuck up `isinstance` checks and use old methods.