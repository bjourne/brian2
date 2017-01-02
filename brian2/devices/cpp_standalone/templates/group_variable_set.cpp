{% extends 'common_group.cpp' %}

{% block maincode %}
	{# USES_VARIABLES { _group_idx } #}
	//// MAIN CODE ////////////
	// scalar code
    const int _vectorisation_idx = -1;
    {{scalar_code|autoindent}}

    {{ openmp_pragma('parallel-static') }}
	for(int _idx_group_idx=0; _idx_group_idx<_num_group_idx; _idx_group_idx++)
	{
	    // vector code
		const int _idx = {{_group_index_var}}[_idx_group_idx];
		const int _vectorisation_idx = _idx;
        {{vector_code|autoindent}}
	}
{% endblock %}
