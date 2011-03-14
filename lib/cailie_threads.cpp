#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sched.h>

#include "cailie.h"
#include "cailie_internal.h"
#include "cailie_threads.h"

#define HALT_COMMAND -1
#define START_LOG_COMMAND -2
#define STOP_LOG_COMMAND -3

struct CaThreadsPacket {
	int target_node;
	int data_id;
	size_t size;
	CaThreadsPacket *next;
};

struct CaThreadsData {
	CaThreadsProcess *process;
	InitFn *init_fn;
};

CaThreadsProcess::CaThreadsProcess(CaThreadsModule *module, int process_id) :
  CaProcess(process_id), _module(module), _packet(NULL) {
		pthread_mutex_init(&_lock, NULL);
}

CaThreadsProcess::~CaThreadsProcess()
{
    pthread_mutex_destroy(&_lock);
}

size_t CaThreadsProcess::get_reserved_prefix_size()
{
	return sizeof(CaThreadsPacket);
}

void CaThreadsProcess::queue_add(CaThreadsPacket *packet)
{
	pthread_mutex_lock(&_lock);
	packet->next = _packet;
	_packet = packet;
	pthread_mutex_unlock(&_lock);
}

void CaThreadsProcess::send(CaContext *ctx, int target, int data_id, void *data, size_t size)
{
	CaThreadsPacket *packet = (CaThreadsPacket *) data;
	packet->target_node = target;
	packet->data_id = data_id;
	packet->size = size;
	_module->get_process(ca_node_to_process(target))->queue_add(packet);
}

void CaThreadsProcess::send_to_all(CaContext *ctx, int data_id, const void *data, size_t size)
{
	int t;
	int source = ctx->node();
	size_t prefix = get_reserved_prefix_size();
 	for (t=0; t < _module->get_nodes_count(); t++) {
		if (t == source) {
			continue; // Don't send the message to self
		}
		char *d = (char*) malloc(prefix + size);
		// ALLOCTEST
		memcpy(d + prefix, data, size);
		send(ctx, t, data_id, d, size);
	}
}

void CaThreadsProcess::quit(CaContext *ctx)
{
	int dummy;
	send_to_all(ctx, HALT_COMMAND, &dummy, 0);
}


void CaThreadsProcess::start_logging(CaContext *ctx, const std::string& logname)
{
	init_log(logname);
	send_to_all(ctx, START_LOG_COMMAND, logname.c_str(), logname.size() + 1);
}

void CaThreadsProcess::stop_logging(CaContext *ctx)
{
	stop_log();
	int dummy;
	send_to_all(ctx, STOP_LOG_COMMAND, &dummy, 0);
}

void CaThreadsProcess::add_context(CaContext* ctx)
{
    _contexts[ctx->node()] = ctx;
}

void CaThreadsProcess::start(InitFn *init_fn)
{
	CaContextsMap::iterator i;
	for (i = _contexts.begin(); i != _contexts.end(); ++i) {
	     init_fn(i->second);
	}
	_running_nodes = _contexts.size();
	start_scheduler();
}

static void * ca_threads_starter(void *data)
{
	CaThreadsData *d = (CaThreadsData*) data;
	d->process->start(d->init_fn);
	return NULL;
}

int CaThreadsProcess::recv()
{
	CaThreadsPacket *packet;
	pthread_mutex_lock(&_lock);
	packet = _packet;
	_packet = NULL;
	pthread_mutex_unlock(&_lock);

	if (packet == NULL) {
		return 0;
	}

	if (_logger) {
	    _logger->log_receive();
	}

	while(packet) {
		int node = packet->target_node;
		if (packet->data_id < 0) {
			if (packet->data_id == HALT_COMMAND) {
				_module->get_context(node)->halt();
			} else if (packet->data_id == START_LOG_COMMAND) {
				init_log((char*) (packet + 1));
			} else if (packet->data_id == STOP_LOG_COMMAND) {
				stop_log();
			}
		} else {
			_module->get_context(node)->_call_recv_fn(packet->data_id, packet + 1, packet->size);
		}
		CaThreadsPacket *p = packet->next;
		free(packet);
		packet = p;
	}
	return 1;
}

int CaThreadsModule::main(int nodes, InitFn *init_fn)
{
	if (ca_process_count < 1 || ca_process_count > nodes) {
		ca_process_count = nodes;
	}

	assert(nodes > 0);
	nodes_count = nodes;
	int t;
	pthread_t threads[nodes];
	CaThreadsData data[nodes];

	CaThreadsProcess *processes[ca_process_count];
	_processes = processes;

	for (t = 0; t < ca_process_count; t++) {
	    processes[t] = new CaThreadsProcess(this, t);
	}

	CaContext *contexts[nodes];
	this->_contexts = contexts;
	for (t = 0; t < nodes; t++) {
		CaThreadsProcess *process = processes[ca_node_to_process(t)];
		contexts[t] = new CaContext(t, process);
		process->add_context(contexts[t]);
	}

	for (t = 0; t < ca_process_count; t++) {
		data[t].process = processes[t];
		data[t].init_fn = init_fn;
		/* FIXME: Check returns code */
		pthread_create(&threads[t], NULL, ca_threads_starter, &data[t]);
	}

	for (t = 0; t < ca_process_count; t++) {
		pthread_join(threads[t], NULL);
	}

	for (t = 0; t < nodes; t++) {
	    delete contexts[t];
	}

	for (t = 0; t < ca_process_count; t++) {
	    delete processes[t];
	}

	// TODO: destroy nonempty places
	return 0;
}

void CaThreadsProcess::idle() {
	sched_yield();
}
