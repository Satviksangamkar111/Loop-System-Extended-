from typing import List, Any


def filter_integers(values: List[Any]) -> List[int]:
    """ Filter given list of any python values only for integers
    >>> filter_integers(['a', 3.14, 5])
    [5]
    >>> filter_integers([1, 2, 3, 'abc', {}, []])
    [1, 2, 3]
    """

TARGET: implement this in the ABAP class Z_HUMANEVAL_022 in the given file. Its public section is already correct and must stay as it is: the methods there are the ones to implement, their bodies are empty now. Private helper methods may be added. If the text above is written in another language or names another class or method, its behaviour is what counts.
