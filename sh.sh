rm dist/*
python convdemo.py
python3 -m build
python3 -m twine upload --repository foscat dist/*