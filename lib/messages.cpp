
#include <stdio.h>
#include "messages.h"
#include "process.h"

#ifdef CA_MPI
#include <mpi.h>
#endif

void CaMessageNewNetwork::process(CaThread *thread) 
{
		thread->add_network(network);
}

void CaMessageBarriers::process(CaThread *thread) 
{
	pthread_barrier_wait(barrier1);
	pthread_barrier_wait(barrier2);
}

void CaMessageLogInit::process(CaThread *thread)
{
	#ifdef CA_MPI
	if (thread->get_id() == 0) {
		MPI_Barrier(MPI_COMM_WORLD);
	}
	#endif // CA_MPI

	pthread_barrier_wait(barrier1);
	thread->init_log(logname);

	#ifdef CA_MPI
	if (thread->get_id() == 0) {
		MPI_Barrier(MPI_COMM_WORLD);
	}
	#endif // CA_MPI

	pthread_barrier_wait(barrier2);

	if (thread->get_id() == 0) {
		pthread_barrier_destroy(barrier1);
		pthread_barrier_destroy(barrier2);
		delete barrier1;
		delete barrier2;
	}
}

void CaMessageLogClose::process(CaThread *thread)
{
	thread->close_log();
}
