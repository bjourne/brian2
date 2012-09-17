'''
Defines the :class:`CodeString` object, encapsulating a string of code together
with a namespace. Is used directly for thresholds and resets and is the basis
for :class:`Equations`.
'''

import inspect
from warnings import warn

from sympy import sympify, Symbol, Wild, diff
from sympy.core.sympify import SympifyError

from brian2.units.fundamentalunits import get_dimensions, DimensionMismatchError
from brian2.utils.stringtools import get_identifiers, word_substitute
from brian2.equations.unitcheck import get_default_unit_namespace

__all__ = ['CodeString']

class ResolutionConflictWarning(UserWarning):
    '''
    A warning for situations where an identifier can refer to more than one
    object in the namespaces used for resolving identifiers.
    '''
    pass


class CodeString(object):
    '''
    A class for representing strings and an attached namespace.
    '''

    def __init__(self, code, namespace=None, exhaustive=False, level=0):
        '''
        Creates a new :class:`CodeString`.

        If ``exhaustive`` is not ``False`` (meaning that the namespace for the
        string is explicitly specified), the :class:`CodeString` object saves
        the current local and global namespace for later use in resolving
        identifiers.

        Arguments:

        ``code``:
            The code string, may be an expression or a statement (possibly
            multi-line).

        ``namespace``:
            A mapping (e.g. a dictionary), mapping identifiers (strings) to
            objects. Will be used as a namespace for the ``code``.

        ``exhaustive``:
            If set to ``True``, no local/global namespace will be saved,
            meaning that the given namespace has to be exhaustive (except for
            units). Defaults to ``False``, meaning that the given namespace
            augments the local and global namespace (taking precedence over
            them in case of conflicting definitions).

        '''
        self._code = code
        
        # extract identifiers from the code
        self._identifiers = set(get_identifiers(code))
        
        if namespace is None:
            namespace = {}
        
        self._exhaustive = exhaustive
        
        if not exhaustive:
            frame = inspect.stack()[level + 1][0]
            self._locals = frame.f_locals.copy()
            self._globals = frame.f_globals.copy()
        else:
            self._locals = {}
            self._globals = {}
        
        self._given_namespace = namespace
        
        # The namespace containing resolved references
        self._namespace = None
    
    code = property(lambda self: self._code,
                    doc='The code string')

    exhaustive = property(lambda self: self._exhaustive,
                          doc='Whether the namespace is exhaustively defined')
        
    identifiers = property(lambda self: self._identifiers,
                           doc='Set of identifiers in the code string')
    
    is_resolved = property(lambda self: not self._namespace is None,
                           doc='Whether the external identifiers have been resolved')
        
    namespace = property(lambda self: self._namespace,
                         doc='The namespace resolving external identifiers')    
        
    def resolve(self, internal_variables):
        '''
        Determines the namespace for the given codestring, containing
        resolved references to externally defined variables and functions.

        The resulting namespace includes units but does not include anything
        present in the ``internal variables`` collection. All referenced
        internal variables are included in the CodeString's ``dependency``
        attribute. 
        
        Raises an error if a variable/function cannot be resolved and is
        not contained in ``internal_variables``. Raises a
        :class:``ResolutionConflictWarning`` if there are conflicting
        resolutions.
        '''

        if self.is_resolved:
            raise TypeError('Variables have already been resolved before.')

        unit_namespace = get_default_unit_namespace()
             
        namespace = {}
        for identifier in self.identifiers:
            # We save tuples of (namespace description, referred object) to
            # give meaningful warnings in case of duplicate definitions
            matches = []
            if identifier in self._given_namespace:
                matches.append(('user-defined',
                                self._given_namespace[identifier]))
            if identifier in self._locals:
                matches.append(('locals',
                                self._locals[identifier]))
            if identifier in self._globals:
                matches.append(('globals',
                                self._globals[identifier]))
            if identifier in unit_namespace:
                matches.append(('units',
                               unit_namespace[identifier]))
            
            if identifier in internal_variables:
                # The identifier is an internal variable
                
                if len(matches) == 1:
                    warn(('The name "%s" in the code string "%s" refers to an '
                          'internal variable but also to a variable in the %s '
                          'namespace: %r') %
                         (identifier, self.code, matches[0][0], matches[0][1]),
                         ResolutionConflictWarning)
                elif len(matches) > 1:
                    warn(('The name "%s" in the code string "%s" refers to an '
                          'internal variable but also to variables in the '
                          'following namespaces: %s') %
                         (identifier, self.code, [m[0] for m in matches]),
                         ResolutionConflictWarning)
            else:
                # The identifier is not an internal variable
                if len(matches) == 0:
                    raise ValueError('The identifier "%s" in the code string '
                                     '"%s" could not be resolved.' % 
                                     (identifier, self.code))
                elif len(matches) > 1:
                    # Possibly, all matches refer to the same object
                    first_obj = matches[0][1]
                    if not all([m[1] is first_obj for m in matches]):
                        warn(('The name "%s" in the code string "%s" '
                              'refers to different objects in different '
                              'namespaces used for resolving. Will use '
                              'the object from the %s namespace: %r') %
                             (identifier, self.code, matches[0][0],
                              first_obj))
                
                # use the first match (according to resolution order)
                namespace[identifier] = matches[0][1]
                
        self._namespace = namespace

    def frozen(self):
        '''
        Returns a new :class:`CodeString` object, where all external variables
        are replaced by their floating point values and removed from the
        namespace.
        
        The namespace has to be resolved using the :meth:`resolve` method first.
        
        When called on an object of a subclass, returns an instance of the
        subclass (otherwise an :class:`Expression` would be converted to
        a :class:`CodeString` object after freezing).  
        '''
        
        if not self.is_resolved:
            raise TypeError('Can only freeze resolved CodeString objects.')
        
        #TODO: For expressions, this could be done more elegantly with sympy
        
        new_namespace = self.namespace.copy()
        substitutions = {}
        for identifier in self.identifiers:
            if identifier in new_namespace:
                # Try to replace the variable with its float value
                try:
                    float_value = float(new_namespace[identifier])
                    substitutions[identifier] = str(float_value)
                    # Reference in namespace no longer needed
                    del new_namespace[identifier]
                except (ValueError, TypeError):
                    pass
        
        # Apply the substitutions to the string
        new_code = word_substitute(self.code, substitutions)
        
        # Create a new CodeString object with the new code and namespace
        new_obj = type(self)(new_code, namespace=new_namespace,
                             exhaustive=True)
        new_obj._namespace = new_namespace.copy()
        return new_obj

    def check_linearity(self, variable):
        '''
        Returns whether the expression  is linear with respect to ``variable``,
        assuming that all other variables are constants. The expression should
        not contain any functions.
        '''
        try:
            sympy_expr = sympify(self.code)
        except SympifyError:
            raise ValueError('Expression "%s" cannot be parsed with sympy' %
                             self.code)
    
        x = Symbol(variable)
    
        if not x in sympy_expr:
            return True
    
    #    # This tries to check whether the expression can be rewritten in an a*x + b
    #    # but apparently this does not work very well
    #    a = Wild('a', exclude=[x])
    #    b = Wild('b', exclude=[x])
    #    matches = sympy_expr.match(a * x + b) 
    #
    #    return not matches is None
    
        # This seems to be more robust: Take the derivative with respect to the
        # variable
        diff_f = diff(sympy_expr, x).simplify()
    
        # if the expression is linear, x should have disappeared
        return not x in diff_f 
    
    
    def eval_expr(self, internal_variables):
        '''
        Evaluates the expression ``expr`` in its namespace, augmented by the
        values for the ``internal_variables`` (as a dictionary).
        '''
    
        if not self.is_resolved:
            raise TypeError('Can only evaluate resolved CodeString objects.')
        
        namespace = self.namespace.copy()
        namespace.update(internal_variables)
        return eval(self.code, namespace)
    
    
    def get_expr_dimensions(self, variable_units):
        '''
        Returns the dimensions of the expression by evaluating it in its
        namespace, replacing all internal variables with their units. The units
        have to be given in the mapping ``variable_units``. 
        
        The namespace has to be resolved using the :meth:`resolve` method first.
        
        May raise an DimensionMismatchError during the evaluation.
        '''
        return get_dimensions(self.eval_expr(variable_units))
    
    
    def check_unit_against(self, unit, variable_units):
        '''
        Checks whether the dimensions of the expression match the expected
        dimension of ``unit``. The units of all internal variables have to be
        given in the mapping ``variable_units``. 
        
        The namespace has to be resolved using the :meth:`resolve` method first.
        
        May raise an DimensionMismatchError during the evaluation.
        '''
        expr_dimensions = self.get_expr_dimensions(variable_units)
        expected_dimensions = get_dimensions(unit)
        if not expr_dimensions == expected_dimensions:
            raise DimensionMismatchError('Dimensions of expression does not '
                                         'match its definition',
                                         expr_dimensions, expected_dimensions)
    
    def split_stochastic(self):
        '''
        Splits the expression into a tuple of two :class:`CodeString` objects
        f and g, assuming an expression of the form ``f + g * xi``, where
        ``xi`` is the symbol for the random variable.
        
        If no ``xi`` symbol is present in the code string, a tuple
        ``(self, None)`` will be returned with the unchanged
        :class:`CodeString` object.
        '''
        s_expr = sympify(self.code)
        xi = Symbol('xi')
        if not xi in s_expr:
            return (self, None)
        
        f = Wild('f', exclude=[xi]) # non-stochastic part
        g = Wild('g', exclude=[xi]) # stochastic part
        matches = s_expr.match(f + g * xi)
        if matches is None:
            raise ValueError(('Expression "%s" cannot be separated into stochastic '
                             'and non-stochastic term') % self.code)
    
        f_expr = CodeString(str(matches[f]), namespace=self.namespace.copy(),
                            exhaustive=True)
        g_expr = CodeString(str(matches[g] * xi), namespace=self.namespace.copy(),
                            exhaustive=True)
        
        return (f_expr, g_expr)

    def __str__(self):
        return self.code
    
    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.code)