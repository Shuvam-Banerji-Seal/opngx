/* mt_bench.c — isolate multithreaded deflate scaling per level */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <stdint.h>
#ifdef _OPENMP
#include <omp.h>
#endif
#include "compress.h"

static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}

int main(void){
    int W=256,H=300,N=4000;
    size_t raw=(size_t)H*((size_t)W*4+1);
    uint8_t*scan=malloc(raw);
    unsigned s=12345;
    for(size_t i=0;i<raw;i++){s=s*1103515245+12345;scan[i]=(uint8_t)(s>>16);}
    int levels[]={1,2,3,4,6};
    for(int li=0;li<5;li++){
        for(int ji=0;ji<4;ji++){
            int j=1<<ji;
            double t0=now(); long total=0;
            #pragma omp parallel num_threads(j) reduction(+:total)
            {
                cctx*c=cctx_create(1,levels[li]);
                uint8_t*out=malloc(raw+4096);
                #pragma omp for schedule(dynamic,32)
                for(int i=0;i<N;i++) total+=cctx_compress(c,scan,raw,out,raw+4096);
                cctx_free(c); free(out);
            }
            printf("level=%d jobs=%2d: %7.0f fps\n",levels[li],j,N/(now()-t0));
            fflush(stdout);
        }
    }
    return 0;
}
