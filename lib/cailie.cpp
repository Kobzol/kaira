
#include <iostream>
#include <sstream>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <getopt.h>
#include <assert.h>
#include "cailie.h"
#include "cailie_threads.h"
#include "cailie_sim.h"
#include "cailie_internal.h"

static std::string module_name = "threads";

CaContext::CaContext(int node, CaModule *module) 
{
	_node = node;
	_module = module;
	_halt_flag = false;
}

void CaContext::_init(int iid, int instances, void *places, RecvFn *recv_fn, ReportFn *report_fn) 
{
	_iid = iid;
	_instances = instances;
	_recv_fn = recv_fn;
	_places = places;
	_report_fn = report_fn;
}

void CaContext::_register_transition(int id, TransitionFn *fn)
{
	_transitions.push_back(CaTransition(id, fn));
}


bool CaContext::_find_transition(int id, CaTransition &transition)
{
	std::vector<CaTransition>::iterator i;
	for (i = _transitions.begin(); i != _transitions.end(); i++) {
		if (id == i->get_id()) {
			transition = *i;
			return true;
		}
	}
	return false;
}

static int ca_recv(CaContext *ctx, RecvFn *recv_fn, void *data)
{
	return ctx->_get_module()->recv(ctx, recv_fn, data);
}

void CaModule::start_sheduler(CaContext *ctx) {
	void *data = ctx->_get_places();
	std::vector<CaTransition> transitions = ctx->_get_transitions();
	std::vector<CaTransition>::iterator wt, last_executed;

	RecvFn *recv_fn = ctx->_get_recv_fn();
	wt = transitions.begin() + 1;
	last_executed = transitions.begin();
	for(;;) {
		if (wt == transitions.end()) {
			wt = transitions.begin();
		}
		if (wt == last_executed) {
			if (wt->call(ctx, data)) {
				if (ctx->_check_halt_flag()) {
					return;
				}
				ca_recv(ctx, recv_fn, data);
			} else {
				while(!ca_recv(ctx, recv_fn, data)) { ctx->_get_module()->idle(); }	
			}
		} else {
			if (wt->call(ctx, data)) {
				ca_recv(ctx, recv_fn, data);
				last_executed = wt;
			}
		}
		wt++;
	}
}

void ca_main(int nodes_count, InitFn *init_fn) {
	CaModule *m = NULL;
	if (module_name == "threads") {
		m = new CaThreadsModule();
	}
	if (module_name == "sim") {
		m = new CaSimModule();
	}
	if (m == NULL) {
		fprintf(stderr, "Unknown module '%s'\n", module_name.c_str());
		exit(-1);
	}
	m->main(nodes_count, init_fn);
}

void ca_send(CaContext *ctx, int node, int data_id, void *data, size_t data_size)
{
	ctx->_get_module()->send(ctx, node, data_id, data, data_size);
}

static int ca_set_argument(int params_count, const char **param_names, int **param_data, char *name, char *value)
{
	int t;
	for (t = 0; t < params_count; t++) {
		if (!strcmp(name, param_names[t])) {
			char *err = NULL;
			int i = strtol(value, &err, 10);
			if (*err != '\0') {
				printf("Invalid parameter value\n");
				exit(1);
			}
			(*param_data[t]) = i;
			return t;
		}
	}
	printf("Unknown parameter '%s'\n", name);
	exit(1);
}

void ca_parse_args(int argc, char **argv, int params_count, const char **param_names, int **param_data, const char **param_descs)
{
	int t, c;
	struct option longopts[] = {
		{ "help",	0,	NULL, 'h' },
		{ NULL,		0,	NULL,  0}
	};

	bool setted[params_count];
	for (t = 0; t < params_count; t++) {
		setted[t] = false;
	}

	while ((c = getopt_long (argc, argv, "hp:m:", longopts, NULL)) != -1)
		switch (c) {
			case 'm': {
				module_name = optarg;
			} break;
			case 'h': {
				int max_len = 0;
				for (t = 0; t < params_count; t++) {
					if (max_len > strlen(param_names[t])) {
						max_len = strlen(param_names[t]);
					}
				}
				for (t=0; t < params_count; t++) {
					printf("Parameters:\n");
					printf("%s", param_names[t]);
					for (int s = strlen(param_names[t]); s < max_len; s++) { printf(" "); }
					printf(" - %s\n", param_descs[t]);
				}
				exit(0);
			}
			case 'p': {
				char str[strlen(optarg) + 1];
				strcpy(str, optarg);
				char *s = str;
				while ( (*s) != 0 && (*s) != '=') { s++; }
				if ((*s) == 0) {
					printf("Invalid format of -p\n");
					exit(1);
				}
				*s = 0;
				s++;
				int r = ca_set_argument(params_count, param_names, param_data, str, s);
				setted[r] = true;
			} break;

			case '?':
			default:
				exit(1);
			}
	bool exit_f = false;
	for (t = 0; t < params_count; t++) {
		if (!setted[t]) {
			exit_f = true;
			printf("Mandatory parameter '%s' required\n", param_names[t]);
		}
	}
	if (exit_f) { exit(1); }
}

std::string ca_int_to_string(int i) 
{
	std::stringstream osstream;
	osstream << i;
	return osstream.str();
}

CaOutput::~CaOutput() 
{
	while (!_stack.empty()) {
		delete _stack.top();
		_stack.pop();
	}
}

void CaOutput::child(std::string name) 
{
	CaOutputBlock *block = new CaOutputBlock(name);
	_stack.push(block);
}

CaOutputBlock * CaOutput::back() 
{
	CaOutputBlock *block = _stack.top();
	_stack.pop();
	if (!_stack.empty()) {
		CaOutputBlock *parent = _stack.top();
		parent->add_child(block);
	}
	return block;
}

void CaOutput::set(std::string name, std::string value) 
{
	assert(!_stack.empty());
	CaOutputBlock *block = _stack.top();
	block->set(name, value);
	
}

void CaOutput::set(std::string name, int value)
{
	set(name, ca_int_to_string(value));
}

void CaOutputBlock::set(std::string name, std::string value)
{
	std::pair<std::string,std::string> p(name, value);
	_attributes.push_back(p);
}

void CaOutputBlock::write(FILE *file)
{
	fprintf(file,"<%s", _name.c_str());

	std::vector<std::pair<std::string, std::string> >::iterator i;
	for (i = _attributes.begin(); i != _attributes.end(); i++) {
		fprintf(file, " %s='%s'", (*i).first.c_str(), (*i).second.c_str());
	}

	if (_children.size() > 0) {
		fprintf(file,">");
		std::vector<CaOutputBlock*>::iterator i;
		for (i = _children.begin(); i != _children.end(); i++) {
			(*i)->write(file);
		}
		fprintf(file,"</%s>", _name.c_str());
	} else {
		fprintf(file, " />");
	}
}

CaOutputBlock::~CaOutputBlock()
{
		std::vector<CaOutputBlock*>::iterator i;
		for (i = _children.begin(); i != _children.end(); i++) {
			delete (*i);
		}
}
