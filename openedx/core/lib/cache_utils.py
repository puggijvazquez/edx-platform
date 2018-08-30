"""
Utilities related to caching.
"""
import collections
import cPickle as pickle
import functools
import zlib

from django.utils.encoding import force_text
from edx_django_utils.cache import RequestCache


def request_cached(f):
    """
    A decorator for wrapping a function and automatically handles caching its return value, as well as returning
    that cached value for subsequent calls to the same function, with the same parameters, within a given request.

    Notes:
        - We convert arguments and keyword arguments to their string form to build the cache key, so if you have
          args/kwargs that can't be converted to strings, you're gonna have a bad time (don't do it)
        - Cache key cardinality depends on the args/kwargs, so if you're caching a function that takes five arguments,
          you might have deceptively low cache efficiency.  Prefer function with fewer arguments.
        - We use the default request cache, not a named request cache. The code automatically namespaces the cache
          key with the module and function's name.
        - If you require a named request cache, use the ns_request_cached decorator below. Generally, you would need it
          only if you need control of your own namespaced cache - for example, to clear out your own cache.
        - WATCH OUT: Don't use this decorator for instance methods that take in a "self" argument that changes each
          time the method is called. This will result in constant cache misses and not provide the performance benefit
          you are looking for. Rather, change your instance method to a class method.
        - Benchmark, benchmark, benchmark! if you never measure, how will you know you've improved? or regressed?

    Arguments:
        f (func): the function to wrap

    Returns:
        func: a wrapper function which will call the wrapped function, passing in the same args/kwargs,
              cache the value it returns, and return that cached value for subsequent calls with the
              same args/kwargs within a single request
    """
    return ns_request_cached()(f)


def ns_request_cached(namespace=None, arg_map_function=None, request_cache_getter=None):
    """
    Same as request_cached above, except an optional namespace can be passed in to compartmentalize the cache.

    Arguments:
        namespace (string): An optional namespace to use for the cache.  Useful if the caller wants to manage
            their own sub-cache by, for example, calling RequestCache(namespace=NAMESPACE).clear() for their own
            namespace.
        arg_map_function (function: arg->string): Function to use for mapping the wrapped function's arguments to
            strings to use in the cache key. If not provided, defaults to force_text, which converts the given
            argument to a string.
        request_cache_getter (function: args->RequestCache): Function that returns the RequestCache to use. If not
            provided, defaults to edx_django_utils.cache.RequestCache.  If None, the function's return values are
            not cached.
    """
    def outer_wrapper(f):
        """
        Outer wrapper that decorates the given function

        Arguments:
            f (func): the function to wrap
        """
        def inner_wrapper(*args, **kwargs):
            """
            Wrapper function to decorate with.
            """
            # Check to see if we have a result in cache.  If not, invoke our wrapped
            # function.  Cache and return the result to the caller.
            if request_cache_getter:
                request_cache = request_cache_getter(args)
            else:
                request_cache = RequestCache(namespace)

            if request_cache:
                cache_key = _func_call_cache_key(f, arg_map_function, *args, **kwargs)
                cached_response = request_cache.get_cached_response(cache_key)
                if cached_response.is_found:
                    return cached_response.value

            result = f(*args, **kwargs)

            if request_cache:
                request_cache.set(cache_key, result)

            return result

        return inner_wrapper
    return outer_wrapper


def _func_call_cache_key(func, arg_map_function, *args, **kwargs):
    """
    Returns a cache key based on the function's module
    the function's name, and a stringified list of arguments
    and a query string-style stringified list of keyword arguments.
    """
    arg_map_function = arg_map_function or force_text
    converted_args = map(arg_map_function, args)
    converted_kwargs = map(arg_map_function, reduce(list.__add__, map(list, sorted(kwargs.iteritems())), []))
    cache_keys = [func.__module__, func.func_name] + converted_args + converted_kwargs
    return u'.'.join(cache_keys)


class memoized(object):  # pylint: disable=invalid-name
    """
    Decorator. Caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned
    (not reevaluated).
    https://wiki.python.org/moin/PythonDecoratorLibrary#Memoize

    WARNING: Only use this memoized decorator for caching data that
    is constant throughout the lifetime of a gunicorn worker process,
    is costly to compute, and is required often.  Otherwise, it can lead to
    unwanted memory leakage.
    """

    def __init__(self, func):
        self.func = func
        self.cache = {}

    def __call__(self, *args):
        if not isinstance(args, collections.Hashable):
            # uncacheable. a list, for instance.
            # better to not cache than blow up.
            return self.func(*args)
        if args in self.cache:
            return self.cache[args]
        else:
            value = self.func(*args)
            self.cache[args] = value
            return value

    def __repr__(self):
        """
        Return the function's docstring.
        """
        return self.func.__doc__

    def __get__(self, obj, objtype):
        """
        Support instance methods.
        """
        return functools.partial(self.__call__, obj)


def zpickle(data):
    """Given any data structure, returns a zlib compressed pickled serialization."""
    return zlib.compress(pickle.dumps(data, pickle.HIGHEST_PROTOCOL))


def zunpickle(zdata):
    """Given a zlib compressed pickled serialization, returns the deserialized data."""
    return pickle.loads(zlib.decompress(zdata))


def get_cache(name):
    """
    Return the request cache named ``name``.

    Arguments:
        name (str): The name of the request cache to load

    Returns: dict
    """
    assert name is not None
    return RequestCache(name).data
