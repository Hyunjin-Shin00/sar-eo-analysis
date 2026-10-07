#double precision

import numpy as np
import time
import sys
#sys.path.append('../tools')
#import my2D

# --- PyCUDA initialization
import pycuda.driver as cuda
import pycuda.autoinit
from pycuda.compiler import SourceModule

def iDivUp(a, b):
    return a // b + 1

# modified inv_rhorc_fit_gpu_9comps_LUTaer_am_ts_onestep_relnorm.py

# add aero3 for error in rayleigh reflectance on 2021. 07. 21
# rhorc(rhot-rhor) = Rrs(p0..p3)*trans*PI + p4*aero1 + p5*aero2 + p6*aero3
# aero1 for coastal, aero2  for pacific, aero3 for rayleigh error
# steps for aero1, aero2, aero3 copied from foreward_test.py
# 1)vical=None, ray_fac=0.99, Rrs_g2 spectra from coastal  water, get_rhoa and smoothing
# --> rhoashape=[1.03873,1.26598,1.35286,1.32157,1.30839,1.27859,1.23538,1.20869,1.19534,1.17601,1.15171,1.00000]
# 2) with rhoashape, compute vical
# --> #vical=[1.0493,0.9967,1.0193,1.0071,1.0594,1.0574,1.0012,0.9836,1.0125,0.9802,1.0001,1.0000 ]
# 3) with vical, Rrs_g2 from open sea and ray_fac=0.95?, get_rhoa without  smoothing
# --> 1.45768,1.45725,1.45759,1.51054,1.61379,1.69930,1.34050,1.18396,1.20713,1.04001,1.07453,1.00000
# 4) aero3 ~ (waves[-1]/waves)**4
# --> 26.47054,19.25775,14.37647,9.61571,8.20958,5.86787,3.77268,2.93719,2.60621,2.20526,1.80457,1.00

mod = SourceModule("""
#include <stdio.h>
#include <math.h>
#define DEBUG 0

__device__ static const int nw=7; 
__device__ static const int np=6; //4 iopw's + 2 aero's
__device__ static const int na=np-4;
__device__ static const double wave[nw]={483.2, 562.4, 664.6, 704.8, 739.2, 781.9, 836.6};
__device__ static const double aw[nw]={ 0.0169, 0.0674, 0.4162, 0.7532, 2.6748, 2.6278, 3.5677};

__device__ static const double a1[nw]={1.0, 0.2226, 0.5087, 0.0878, 0.0207, 0.001, 0.0004};
__device__ static const double a2[nw]={1.0, 0.4477, 0.1612, 0.1076, 0.0766, 0.0505, 0.0304};
__device__ static const double a3[nw]={1.,1.,1.,1., 1.,1.,1.};
__device__ static const double bbw[nw]={0.00168, 0.00089, 0.00043, 0.00034, 0.00028, 0.00023, 0.00017};
__device__ static const double bb1[nw]={1.079, 1.0, 0.92, 0.893, 0.872, 0.848, 0.8};
//--bb=bbw+p[3]*power(550./wave, n) with n=exp(-0.5*p[3])
//__device__ static const double transFix[nw]={0.53104887, 0.61597324, 0.67903082, 0.75122552, 0.7748434,  0.81624415,
//    0.85941797, 0.87838258, 0.88626958, 0.89551788, 0.90563733, 0.9284764};
__device__ static const double transFix[nw]={1., 1., 1., 1., 1.,  1.,1.};


 __device__ static const double aeroFix[na][nw]= {
  {1.316, 1.219, 1.122, 1.089, 1.063, 1.034, 1.0}, //wave ^(-0.5)
  {0.617, 0.81, 0.953, 1.034, 1.021, 1.089, 1.0} //glint
 };


__device__ static const double wgt[nw]={1.,1., 1.,1.,1.,1.,1.};
__device__ static const double sumwgt=7.;
__device__ static const double wgt0[nw]={1.,1.,1.,1.,1.,1.,1.};
__device__ static const double sumwgt0=7.;

__device__ static double g1=0.089, g2=0.125;
__device__ static double mpi=3.14159265;

__device__ void anbb(double p[np], double a[nw], double bb[nw])
{
    int ib;
    //double _n;

    for (ib=0;ib<nw;ib++) a[ib] = aw[ib]+a1[ib]*p[0]+a2[ib]*p[1]+a3[ib]*p[2];
    for (ib=0;ib<nw;ib++) bb[ib]= bbw[ib]+bb1[ib]*p[3];
    //_n = exp(-0.5*p[3]);
    //for (ib=0;ib<nw;ib++) bb[ib]= bbw[ib] + p[3]*pow(550./wave[ib],_n);
}

__device__ void dif_anbb(double p[np], double d_a_p0[nw], double d_a_p1[nw], double d_a_p2[nw], double d_bb_p3[nw])
{
    int ib;
    //double _n,d_n_p3;

    for (ib=0;ib<nw;ib++) d_a_p0[ib]=a1[ib];
    for (ib=0;ib<nw;ib++) d_a_p1[ib]=a2[ib];
    for (ib=0;ib<nw;ib++) d_a_p2[ib]=a3[ib];
    for (ib=0;ib<nw;ib++) d_bb_p3[ib]=bb1[ib];
    //_n = exp(-0.5*p[3]);
    //d_n_p3 = -0.5*_n;
    //for (ib=0;ib<nw;ib++) d_bb_p3[ib]
    //    = pow(550./wave[ib],_n)+p[3]*pow(550./wave[ib],_n)*log(550./wave[ib])*d_n_p3;
}

__device__ void func_Rrs(double p[np], double Rrs[nw])
{
    int ib;
    double a[nw], bb[nw], u[nw], rrs[nw];
    anbb(p, a, bb);
    for (ib=0;ib<nw;ib++) u[ib] = bb[ib]/(a[ib]+bb[ib]);
    for (ib=0;ib<nw;ib++) rrs[ib] = (g1+g2*u[ib])*u[ib];
    for (ib=0;ib<nw;ib++) Rrs[ib] = 0.52*rrs[ib]/(1.-1.7*rrs[ib]);
}

__device__ void func_rhorc(double p[np],  double aero[na][nw], double trans[nw], double rhorc[nw])
{
    int ib, ia;
    double Rrs[nw];
    func_Rrs(p,Rrs);
    for (ib=0;ib<nw;ib++) {
        rhorc[ib]=Rrs[ib]*trans[ib]*mpi;
        for (ia=0; ia < na; ia++) rhorc[ib]=rhorc[ib]+p[ia+4]*aero[ia][ib];
        //p[4]*aero[0][ib]+p[5]*aero[1][ib]+p[6]*aero[2][ib];
    }
}
__device__ void cost(double p[np], double aero[na][nw],double trans[nw],double rhorc[nw], double *_cost)
{
    int ib;
    double mod[nw], _d;

    func_rhorc(p, aero, trans,mod);
    *_cost = 0.;
    for (ib=0;ib<nw;ib++) {
        _d=rhorc[ib]-mod[ib];
        *_cost += _d*_d*wgt[ib];
    }
}
__device__ void cost0(double p[np], double aero[na][nw],double trans[nw],double rhorc[nw], double *_cost)
{
    int ib;
    double mod[nw], _d;

    func_rhorc(p, aero, trans,mod);
    *_cost = 0.;
    for (ib=0;ib<nw;ib++) {
        _d=rhorc[ib]-mod[ib];
        *_cost += _d*_d*wgt0[ib];
    }
}

__device__ void error(double p[np], double aero[na][nw],double trans[nw],double rhorc[nw], double err[nw]){
    int ib;
    double mod[nw];

    func_rhorc(p,aero,trans, mod);
    for (ib=0;ib<nw;ib++) err[ib]=mod[ib]-rhorc[ib];
}


__device__ void dif_rhorc(double p[np], double aero[na][nw], double trans[nw],
                double dif_rhorc_p[np][nw])
{
    int ib, ip;
    double a[nw], bb[nw],d_a_p0[nw],d_a_p1[nw],d_a_p2[nw],d_bb_p3[nw];
    double dif_u_p[np-na][nw];
    double dif_Rrs_rrs[nw], dif_rrs_p[np-na][nw];
    double u[nw],dif_rrs_u[nw] , rrs[nw];

	anbb(p, a, bb);
	dif_anbb(p,d_a_p0,d_a_p1,d_a_p2,d_bb_p3);

	for (ib=0;ib<nw;ib++) dif_u_p[0][ib] = -bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_a_p0[ib]);
	for (ib=0;ib<nw;ib++) dif_u_p[1][ib] = -bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_a_p1[ib]);
	for (ib=0;ib<nw;ib++) dif_u_p[2][ib] = -bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_a_p2[ib]);

	for (ib=0;ib<nw;ib++) dif_u_p[3][ib] = d_bb_p3[ib]/(a[ib]+bb[ib])-bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_bb_p3[ib]);

	for (ib=0;ib<nw;ib++) u[ib] = bb[ib]/(a[ib]+bb[ib]);
	for (ib=0;ib<nw;ib++) dif_rrs_u[ib] = g2*u[ib] + g1+g2*u[ib];

	for (ib=0;ib<nw;ib++) rrs[ib]=(g1+g2*u[ib])*u[ib];
	for (ib=0;ib<nw;ib++) dif_Rrs_rrs[ib] = 0.52/(1.-1.7*rrs[ib]) - 0.52*rrs[ib]/pow((1.-1.7*rrs[ib]),2) * (-1.7);
    for (ip=0;ip<np-na;ip++) for (ib=0;ib<nw;ib++) dif_rrs_p[ip][ib] =dif_rrs_u[ib]*dif_u_p[ip][ib];

    for (ip=0;ip<np-na;ip++) for (ib=0;ib<nw;ib++) dif_rhorc_p[ip][ib] =dif_Rrs_rrs[ib]*dif_rrs_p[ip][ib]*trans[ib]*mpi;
    for (ip=np-na;ip<np;ip++) for (ib=0;ib<nw;ib++) dif_rhorc_p[ip][ib] = aero[ip-np+na][ib];
}


__device__ void dif_cost(double p[np], double aero[na][nw], double trans[nw],double rhorc[nw],
                        double dif_cost_p[np])
{
    double dif_rhorc_p[np][nw];
    double mod[nw];
    int ip, ib;

    dif_rhorc(p,aero,trans,dif_rhorc_p);
    func_rhorc(p,aero,trans,mod);
	for (ip=0;ip<np;ip++) {
        dif_cost_p[ip]=0.;
        for (ib=0;ib<nw;ib++) dif_cost_p[ip] += 2.*((mod[ib]-rhorc[ib])*dif_rhorc_p[ip][ib])*wgt[ib];
        }
}

__device__ void dif_cost0(double p[np], double aero[na][nw], double trans[nw],double rhorc[nw],
                        double dif_cost_p[np])
{
    double dif_rhorc_p[np][nw];
    double mod[nw];
    int ip, ib;

    dif_rhorc(p,aero,trans,dif_rhorc_p);
    func_rhorc(p,aero,trans,mod);
    for (ip=0;ip<np;ip++) {
        dif_cost_p[ip]=0.;
        for (ib=0;ib<nw;ib++) dif_cost_p[ip] += 2.*((mod[ib]-rhorc[ib])*dif_rhorc_p[ip][ib])*wgt0[ib];
        }
}

__device__ void p_range(double  p[np], double rhorc[nw]){
    int ip;
    //double maxrhoa, _rhoa;
    double mf;
    for  (ip=0; ip<np; ip++) p[ip]= ((p[ip] > 0.) ? p[ip] : 0.);

    mf=5.; //5.;
    p[1]= (p[1]<mf*p[3] ? p[1]: mf*p[3]);
    p[2]= (p[2]<mf*p[3] ? p[2]: mf*p[3]);

    //maxrhoa = (rhorc[0] < rhorc[nw-1] ? rhorc[0] : rhorc[nw-1]);
    //_rhoa = 0.;
    //for (ip=4; ip<np; ip++) _rhoa = _rhoa + p[ip];
    //if (_rhoa > maxrhoa) {
    //    for (ip=4; ip<np; ip++) p[ip]=p[ip]*maxrhoa/_rhoa;
    //}
}

__device__ void normsq(double vec[np], double *nsq) {
    int ip;
    *nsq=0.;
    for  (ip=0; ip<np; ip++) *nsq += vec[ip]*vec[ip];
}

//__device__ void gamma(double p0[np],double pp[np],double dif_at_p0[np],double dif_at_pp[np], double * gam){
//    int ip;
//    double _tmp, nsq,_dif[np];
//    _tmp=0.;
//    for (ip=0;ip<np;ip++) _tmp += (p0[ip]-pp[ip])*(dif_at_p0[ip]-dif_at_pp[ip]);
//    for (ip=0;ip<np;ip++) _dif[ip]= dif_at_p0[ip]-dif_at_pp[ip];
//    normsq(_dif, &nsq);
//    *gam = fabs(_tmp)/nsq;
//}

__device__ void averelerr(double p[np], double aero[na][nw], double  trans[nw], double rhorc[nw], double *_relerr){
    int iw;
    double model[nw], sum;

    func_rhorc(p,aero,trans,model);
    sum=0.;
    //for (iw=0;iw<nw;iw++) sum += pow( (model[iw]-rhorc[iw])/rhorc[iw] ,2);
    //*_relerr = sqrt(sum/nw);
    for (iw=0;iw<nw;iw++) sum += pow( (model[iw]-rhorc[iw])/rhorc[iw]*wgt[iw] ,2);
    *_relerr = sqrt(sum/sumwgt);
}

__device__ void base_subtraction(double rhorc[nw], int bd1, int bd2, int o_bd1,int o_bd2, double *hgt){
    double baseline1, baseline2;
    baseline1= (rhorc[bd1]-rhorc[bd2])/(wave[bd1]-wave[bd2])*(wave[o_bd1]-wave[bd2])+rhorc[bd2];
    baseline2= (rhorc[bd1]-rhorc[bd2])/(wave[bd1]-wave[bd2])*(wave[o_bd2]-wave[bd2])+rhorc[bd2];
    *hgt=rhorc[o_bd1]-baseline1+rhorc[o_bd2]-baseline2;
}



__device__ void Adam_update(double m[np], double v[np], double dif_cost_p0[np], int iter, double p0[np], double p1[np]){
    const double beta1=0.9, beta2=0.999, eps=1.e-8;
    int ip;
    double m_hat, v_hat;
    double learning_rate=0.01;//0.015

    for (ip=0;ip<np;ip++) {
        m[ip]=beta1*m[ip]+(1.-beta1)*dif_cost_p0[ip];
        v[ip]=beta2*v[ip]+(1.-beta2)*dif_cost_p0[ip]*dif_cost_p0[ip];

        m_hat=m[ip]/(1.-pow(beta1, iter+1.));
        v_hat=v[ip]/(1.-pow(beta2, iter+1.));

        p1[ip]=p0[ip]-learning_rate * m_hat/(sqrt(v_hat)+eps);
    } 
}

__device__ void compute_Rrs_f(double rhorc[nw], double p[np],  double aero[na][nw], double trans[nw], double Rrs[nw] )
{
    int ib, ia;
    float _aero;
    for (ib=0;ib<nw;ib++){
        _aero=0.;
        for (ia=0; ia < na; ia++) _aero = _aero + p[4+ia]*aero[ia][ib];
        Rrs[ib]=(rhorc[ib]-_aero)/trans[ib]/mpi;
    } 
}

// __device__ static const int nw_f=7;
__device__ static const int np_f=5;
__device__ static const double wgt_f[nw]={1.0,1.0,1.0,1.0,1.0,1.0,1.0};
__device__ static const double sumwgt_f=7.;

__device__ void anbb_f(double p[np_f], double a[nw], double bb[nw])
{
    int ib;
    //double _n;

    for (ib=0;ib<nw;ib++) a[ib] = aw[ib]+a1[ib]*p[0]+a2[ib]*p[1]+a3[ib]*p[2];

    for (ib=0;ib<nw;ib++) bb[ib]= bbw[ib]+bb1[ib]*p[3];
    //_n=expf(-0.5*p[3]); //_n as function of bbp on 2021.06.21
    //for (ib=0;ib<nw;ib++) bb[ib]= bbw[ib]+p[3]*pow(wave[5]/wave[ib], _n);
}
__device__ void dif_anbb_f(double p[np_f], double d_a_p0[nw], double d_a_p1[nw], double d_a_p2[nw], double d_bb_p3[nw])
{
    int ib;
    double _n,d_n_p3;
    for (ib=0;ib<nw;ib++) d_a_p0[ib]=a1[ib];
    for (ib=0;ib<nw;ib++) d_a_p1[ib]=a2[ib];
    for (ib=0;ib<nw;ib++) d_a_p2[ib]=a3[ib];
    for (ib=0;ib<nw;ib++) d_bb_p3[ib]=bb1[ib];
    //_n=expf(-0.5*p[3]);
    //d_n_p3 = -0.5*_n;
    //for (ib=0;ib<nw;ib++) d_bb_p3[ib]=pow(wave[5]/wave[ib], _n)+ 
    //    p[3]*pow(wave[5]/wave[ib], _n)*log(wave[5]/wave[ib])*d_n_p3;
}
__device__ void func_Rrs_f(double p[np_f], double Rrs[nw])
{
    int ib;
    double a[nw], bb[nw], u[nw], rrs[nw];
    anbb_f(p, a, bb);
    for (ib=0;ib<nw;ib++) u[ib] = bb[ib]/(a[ib]+bb[ib]);
    for (ib=0;ib<nw;ib++) rrs[ib] = (g1+g2*u[ib])*u[ib];
    for (ib=0;ib<nw;ib++) Rrs[ib] = 0.52*rrs[ib]/(1.-1.7*rrs[ib])+p[4];
}

__device__ void cost_f(double p[np_f], double Rrs[nw], double *_cost)
{
    int ib;
    double mod[nw], _d;

    func_Rrs_f(p, mod);
    *_cost = 0.;
    for (ib=0;ib<nw;ib++) {
        _d=(Rrs[ib]-mod[ib])*wgt_f[ib];
        *_cost += _d*_d;
    }
}

__device__ void error_f(double p[np_f], double Rrs[nw], double err[nw]){
    int ib;
    double mod[nw];

    func_Rrs_f(p,mod);
    for (ib=0;ib<nw;ib++) err[ib]=Rrs[ib]-mod[ib];
}

__device__ void dif_Rrs_f(double p[np_f], double dif_Rrs_p[np_f][nw])
{
    int ib,ip;
    double a[nw], bb[nw],d_a_p0[nw],d_a_p1[nw],d_a_p2[nw],d_bb_p3[nw];
    double dif_u_p[4][nw]; 
    double dif_Rrs_rrs[nw], dif_rrs_p[4][nw]; //dif_rrs_p0[nw], dif_rrs_p1[nw], dif_rrs_p2[nw], dif_rrs_p3[nw];
    double u[nw],dif_rrs_u[nw], rrs[nw];

    anbb_f(p, a, bb);
    dif_anbb_f(p,d_a_p0,d_a_p1,d_a_p2,d_bb_p3);

    for (ib=0;ib<nw;ib++) dif_u_p[0][ib] = -bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_a_p0[ib]);
    for (ib=0;ib<nw;ib++) dif_u_p[1][ib] = -bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_a_p1[ib]);
    for (ib=0;ib<nw;ib++) dif_u_p[2][ib] = -bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_a_p2[ib]);
    for (ib=0;ib<nw;ib++) dif_u_p[3][ib] = d_bb_p3[ib]/(a[ib]+bb[ib])-bb[ib]/(a[ib]+bb[ib])/(a[ib]+bb[ib])*(d_bb_p3[ib]);

    for (ib=0;ib<nw;ib++) u[ib] = bb[ib]/(a[ib]+bb[ib]);
    for (ib=0;ib<nw;ib++) dif_rrs_u[ib] = g2*u[ib] + g1+g2*u[ib];

    for (ib=0;ib<nw;ib++) rrs[ib]=(g1+g2*u[ib])*u[ib];
    for (ib=0;ib<nw;ib++) dif_Rrs_rrs[ib] = 0.52/(1.-1.7*rrs[ib]) - 0.52*rrs[ib]/pow((1.-1.7*rrs[ib]),2) * (-1.7);
    for (ip=0;ip<4;ip++){
        for (ib=0;ib<nw;ib++) dif_rrs_p[ip][ib] =dif_rrs_u[ib]*dif_u_p[ip][ib];
    }
    for (ip=0;ip<4;ip++) {
        for (ib=0;ib<nw;ib++) dif_Rrs_p[ip][ib] =dif_Rrs_rrs[ib]*dif_rrs_p[ip][ib];
    }
    for (ib=0;ib<nw;ib++) dif_Rrs_p[4][ib] =1.0;
}

__device__ void dif_cost_f(double p[np_f], double Rrs[nw], double dif_cost_p[np_f] )
{
    double dif_Rrs_p[np_f][nw];
    double mod[nw];
    int ip, ib;

    dif_Rrs_f(p,dif_Rrs_p); //

    func_Rrs_f(p,mod);
    for (ip=0;ip<np_f;ip++) {
        dif_cost_p[ip]=0.;
        for (ib=0;ib<nw;ib++) dif_cost_p[ip] += 2.*((mod[ib]-Rrs[ib])*dif_Rrs_p[ip][ib]*wgt_f[ib]);
    }
}

__device__ void p_range_f(double  p[np_f]){
    int ip;
    double mf;
    for  (ip=0; ip<np_f-1; ip++) p[ip]= ((p[ip] > 0.) ? p[ip] : 0.);

    mf=3.; //5.;
    p[1]= (p[1]<mf*p[3] ? p[1]: mf*p[3]);
    p[2]= (p[2]<mf*p[3] ? p[2]: mf*p[3]);
}

__device__ void normsq_f(double vec[np_f], double *nsq) {
    int ip;
    *nsq=0.;
    for  (ip=0; ip<np_f; ip++) *nsq += vec[ip]*vec[ip];
}

__device__ void gamma_f(double p0[np_f],double pp[np_f],double dif_at_p0[np_f],double dif_at_pp[np_f], double * gam){
    int ip;
    double _tmp, nsq,_dif[np_f];
    _tmp=0.;
    for (ip=0;ip<np_f;ip++) _tmp += (p0[ip]-pp[ip])*(dif_at_p0[ip]-dif_at_pp[ip]);
    for (ip=0;ip<np_f;ip++) _dif[ip]= dif_at_p0[ip]-dif_at_pp[ip];
    normsq_f(_dif, &nsq);
    *gam = fabs(_tmp)/(nsq+1.e-20);
}

__device__ void averelerr_f(double p[np_f], double Rrs[nw], double *_relerr){
    int iw;
    double model[nw], sum, ave;

    func_Rrs_f(p,model); 
    ave=0.;
    for (iw=0;iw<nw;iw++) ave += Rrs[iw]*wgt_f[iw];
    ave=ave/sumwgt_f;
    sum=0.;
    for (iw=0;iw<nw;iw++) sum += pow( (model[iw]-Rrs[iw])/ave*wgt_f[iw] ,2);

    *_relerr = sqrt(sum/sumwgt_f);
}

__device__ void relative_diff_in_norm(double Rrs0[nw], double Rrs1[nw], double Rrs2[nw], double *relnorm){
    int iw;
    double sum1=0., sum2=0.;
    for (iw=0;iw<nw;iw++) sum1 += (Rrs2[iw]-Rrs1[iw])*(Rrs2[iw]-Rrs1[iw]);
    for (iw=0;iw<nw;iw++) sum2 += Rrs0[iw]*Rrs0[iw];
    *relnorm = sqrt(sum1/sum2); 
}


__device__ void base_subtraction_1bd(double rhorc[nw], int bd1, int bd2, int o_bd1, double *hgt){
    double baseline1;
    baseline1= (rhorc[bd1]-rhorc[bd2])/(wave[bd1]-wave[bd2])*(wave[o_bd1]-wave[bd2])+rhorc[bd2];
    *hgt=rhorc[o_bd1]-baseline1;
}

__global__ void gpu_rhorc_fitting_onestep(
                    double * __restrict__ iop,
                    double * __restrict__ rhorc_mod,
                    double * __restrict__ Rrs_mod,
                    double * __restrict__ relerr,
                    int * __restrict__ niter,
                    double * __restrict__ Rrs_out,

                    double * __restrict__ iop_f,
                    double * __restrict__ Rrs_mod_f,
                    double * __restrict__ relerr_f,
                    int * __restrict__ niter_f,
                    double * __restrict__ relnormdif_f,

                    const double * __restrict__ rhorc,
                    const double * __restrict__ lutratio,
                    const double * __restrict__ amratio,
                    const unsigned char * __restrict__ mask,
                    const int M, const int N)
{
    const int x = threadIdx.x + blockIdx.x * blockDim.x;
    const int y = threadIdx.y + blockIdx.y * blockDim.y;
    const long tid = x+y*N;

    const int maxiter=2000;//10000;//5000;
    const double reltol = 1.0e-8;

    double _rhorc[nw],_mod[nw],p0[np],p1[np],dif_cost_p0[np],dif_cost_p1[np],_mod_Rrs[nw];
    double c0,c1,_relerr, _relerr_p, _relerr_min;
    int ib,ip,ip1,iter, iter_min;
    double alpha = 0.02; //0.01
    double pp[np], pmin[np];
    double _lutratio[nw],  aero[na][nw], _amratio, trans[nw];
    
    double m[np],v[np];

    //==below declaration for inwater optimization 
    double _Rrs_f[nw], _mod_f[nw],p0_f[np_f],p1_f[np_f],dif_cost_p0_f[np_f],dif_cost_p1_f[np_f];
    //double momentum[np_f];
    const int maxiter_f=1000;
    const double tol = 1.0e-20;
    double relnorm_tmp;
    double _Rrs_f_1[nw], _Rrs_f_2[nw];

    if (y >= M || x>=N ) return;

    /**debugging*/
    #if DEBUG
        if (x!=2302) return;
        if (y!=1729) return;
    #endif

    if (mask[tid] !=0) return;

    for (ib=0;ib<nw;ib++) _rhorc[ib] = rhorc[tid*nw+ib];
    for (ib=0;ib<nw;ib++) _lutratio[ib] = lutratio[tid*nw+ib];
    _amratio=amratio[tid];

    for (ip=0;ip<na;ip++) {
        for (ib=0;ib<nw;ib++) aero[ip][ib]= aeroFix[ip][ib]*_lutratio[ib];
    }
    for (ib=0;ib<nw;ib++) trans[ib]=pow(transFix[ib],_amratio);
    
    for (ip=0;ip<np;ip++) p0[ip]=0.01; //initialize


    for (ip=0;ip<np;ip++) m[ip]=0.0; //initialize
    for (ip=0;ip<np;ip++) v[ip]=0.0; //initialize
    
    cost(p0,aero, trans, _rhorc, &c0);
    dif_cost(p0, aero,trans,_rhorc, dif_cost_p0);
    averelerr(p0,aero,trans, _rhorc, &_relerr);
    _relerr_min=_relerr;
    iter_min=0;

    //for (ip=0;ip<np;ip++) p1[ip] = p0[ip] - dif_cost_p0[ip]*alpha;
    Adam_update(m,v,dif_cost_p0,0,p0,p1);
    
    p_range(p1,_rhorc);
    cost(p1,aero, trans, _rhorc, &c1);
    dif_cost(p1, aero,trans, _rhorc, dif_cost_p1);
    _relerr_p = _relerr;
    averelerr(p1,aero, trans, _rhorc, &_relerr);

    for (iter=0; iter<maxiter; iter++) {

        //if (_relerr<0.01 || fabs(c1 -c0)/c0 < reltol ) break;
        if ((_relerr<0.01) ||
           (iter>1000 && ( (iter>iter_min+50 && _relerr>_relerr_min*1.1) || (iter>iter_min+200) )) ||
           (_relerr<0.02 && fabs(_relerr-_relerr_p) <1.e-7 && fabs(c1-c0)<1.e-10 )) {
                //printf("%d %e %e %e %e\\n ",iter,_relerr,_relerr_p,c0,c1);
                break;
        }
        //if (iter>5000 && _relerr>_relerr_min+0.3) break;

        //gamma(p1,p0,dif_cost_p1,dif_cost_p0, &alpha);
        for (ip=0;ip<np;ip++) pp[ip]=p0[ip];
        for (ip=0;ip<np;ip++) p0[ip]=p1[ip];
        c0=c1;
        dif_cost(p0, aero, trans,_rhorc, dif_cost_p0);
        
        Adam_update(m,v,dif_cost_p0,iter,p0,p1);
        //for (ip=0;ip<np;ip++) p1[ip] = p0[ip] - dif_cost_p0[ip]*alpha*0.7+0.3*(p0[ip]-pp[ip]); //momentum no work for ex clear water
        p_range(p1,_rhorc);
        
        cost(p1,aero,trans,_rhorc,&c1);
        //dif_cost(p1,aero,trans,_rhorc,dif_cost_p1);
        _relerr_p = _relerr;
        averelerr(p1, aero,trans,_rhorc, &_relerr);
        if(_relerr < _relerr_min) {
            iter_min=iter;
            _relerr_min=_relerr;
            for (ip=0;ip<np;ip++) pmin[ip] = p1[ip];
        }

        /**for debugging */
        #if 0 //DEBUG
        printf("%d %e %e %f ", iter, _relerr, c1, alpha);
        for (ip=0;ip<np;ip++) printf("%f ", p1[ip]);
        printf("\\n");
        #endif

    }
    func_rhorc(pmin,aero,trans,_mod);
    averelerr(pmin, aero,trans,_rhorc, &_relerr_min);

    /* Debugging
    if ((x==441) & y==2224) {
            for (ib=0;ib<nw;ib++) printf("%f ", _rhorc[ib]);
            printf("\\n");
            for (ip=0;ip<np;ip++) printf("%f ", p1[ip]);
            printf("\\n");
            }
    if (( x==442) & y==2224) {
            for (ib=0;ib<nw;ib++) printf("%f ", _rhorc[ib]);
            printf("\\n");
            for (ip=0;ip<np;ip++) printf("%f ", p1[ip]);
            printf("\\n");
            }
    */

    
    for (ip=0;ip<np;ip++) iop[tid*np+ip]=pmin[ip];
    for (ib=0;ib<nw;ib++) rhorc_mod[tid*nw+ib]=_mod[ib];
    func_Rrs(pmin, _mod_Rrs);
    for (ib=0;ib<nw;ib++) Rrs_mod[tid*nw+ib]=_mod_Rrs[ib];
    relerr[tid]=_relerr_min;
    niter[tid]=iter; //_min;

    //==compute Rrs_f
    compute_Rrs_f(_rhorc, pmin, aero, trans, _Rrs_f);
    for (ib=0;ib<nw;ib++) Rrs_out[tid*nw+ib]=_Rrs_f[ib];

    //p0_f initialize
    for (ip=0;ip<np_f-1;ip++) p0_f[ip]=pmin[ip];
    p0_f[np_f-1]=0.;
    
    //==fit to _Rrs_f
    cost_f(p0_f, _Rrs_f, &c0);
    dif_cost_f(p0_f, _Rrs_f, dif_cost_p0_f);
    alpha=0.1;
    for (ip=0;ip<np_f;ip++) p1_f[ip] = p0_f[ip] - dif_cost_p0_f[ip]*alpha;
    p_range_f(p1_f);
    cost_f(p1_f, _Rrs_f, &c1);
    dif_cost_f(p1_f, _Rrs_f, dif_cost_p1_f);
    averelerr_f(p1_f, _Rrs_f, &_relerr);
    for (iter=0; iter<maxiter_f; iter++) {
        if (_relerr<0.02 || iter>maxiter/2 & (fabs(c1 -c0) < tol ) ) break;
        //if (_relerr<0.01  ) break;
        gamma_f(p1_f,p0_f,dif_cost_p1_f,dif_cost_p0_f, &alpha);
        //for (ip=0;ip<np_f;ip++) momentum[ip]=p1_f[ip]-p0_f[ip];
        for (ip=0;ip<np_f;ip++) p0_f[ip]=p1_f[ip];
        c0=c1;
        dif_cost_f(p0_f, _Rrs_f, dif_cost_p0_f);
        for (ip=0;ip<np_f;ip++) p1_f[ip] = p0_f[ip] - dif_cost_p0_f[ip]*alpha;// +0.5*momentum[ip];
        p_range_f(p1_f);
        cost_f(p1_f,_Rrs_f,&c1);
        dif_cost_f(p1_f,_Rrs_f,dif_cost_p1_f);
        averelerr_f(p1_f, _Rrs_f, &_relerr);
    }

    func_Rrs_f(p1_f,_mod_f);
    for (ib=0;ib<nw;ib++) Rrs_mod_f[tid*nw+ib]=_mod_f[ib];


    for (ip=0;ip<np_f;ip++) iop_f[tid*np_f+ip]=p1_f[ip];

    relerr_f[tid]=_relerr;
    niter_f[tid]=iter;


    for (ip=0; ip < np_f-1; ip++) { //aph, ag, ad, bbp
        for (ip1=0; ip1<np_f; ip1++) p0_f[ip1]=p1_f[ip1];
        p0_f[ip] = 0.9*p1_f[ip]; //10 percent increase
        func_Rrs_f(p0_f, _Rrs_f_1);
        p0_f[ip] = 1.1*p1_f[ip];
        func_Rrs_f(p0_f, _Rrs_f_2);
        relative_diff_in_norm(_mod_f, _Rrs_f_1, _Rrs_f_2, &relnorm_tmp);
        relnormdif_f[tid*(np_f-1)+ip]= relnorm_tmp*5.;
    }
}
""")

import matplotlib.pyplot as plt
if __name__=="__main__":
    # wave=[381.0, 412.5, 443.8, 490.7, 510.5, 555.2, 620.0, 660.1, 680.1, 709.1,745.5, 864.1]
    # wave=np.array(wave)
    # a2=np.exp(-0.014*(wave-440.))
    # print(a2)
    #
    # exit()
    npix=1
    nlin=1
    bds=[0,1,2,3,4,5,6]
    mask=np.zeros((nlin,npix),dtype='uint8')

    _s='0.07903 0.07976 0.07272 0.07445 0.06848 0.07820 0.06697'
    _s='0.10014 0.12070 0.08536 0.07233 0.07050 0.07739 0.06671'
    _s='0.07997 0.07842 0.07422 0.07192 0.07214 0.06896 0.07172'
    
    # _s='0.08083 0.07988 0.06946 0.05713 0.05766 0.05002 0.05130'
    _s='0.09691 0.09856 0.09413 0.08411 0.08612 0.07860 0.07984'

    _rhorc=np.array(_s.split()).astype(np.float64)
    # _rhorc[-2] *=1.1
    # _rhorc[3] *= 1.07
    
    if 0: #taking directionality of LUTaer Qu. transmittance?
        print('think later')
    else:
        _r=np.ones(len(bds),dtype=np.float64)
        am_r=1.
        
    amratio=np.full([nlin,npix],am_r,dtype=np.float64)
       
    rhorc_all=_rhorc
    rhorc = [_rhorc[bds]]

    if nlin*npix>1:
        for i  in range(1,nlin*npix):
            rhorc.append(_rhorc[bds])
    rhorc = np.reshape(rhorc,(nlin,npix,-1))
    print('rhorc: '+' '.join([f'{_:.5f}' for _ in rhorc[0,0,:]]))

    LUTratio=[_r[bds]] #!!!!

    if nlin*npix>1:
        for i  in range(1,nlin*npix):
            LUTratio.append(_r[bds])
    LUTratio = np.reshape(LUTratio,(nlin,npix,-1))
    print('LUTratio: '+' '.join([f'{_:.5f}' for _ in LUTratio[0,0,:]]))
    
    
    niops=6
    mask = np.zeros((nlin,npix), dtype=np.uint8)
    iop = np.zeros((nlin,npix,niops),dtype=np.float64)
    rhorc_mod = np.zeros_like(rhorc)
    Rrs_mod = np.zeros_like(rhorc)
    relerr=np.zeros((nlin,npix),dtype=np.float64)
    niter=np.zeros((nlin,npix),dtype=np.int32)
    Rrs_out = np.zeros_like(rhorc)

    niop_f=5 #second optimization for iopw+1 comps
    iop_f = np.zeros((nlin,npix,niop_f),dtype=np.float64)
    Rrs_mod_f = np.zeros_like(rhorc)
    relerr_f=np.zeros((nlin,npix),dtype=np.float64)
    niter_f=np.zeros((nlin,npix),dtype=np.int32)
    

    niopw=4
    relnormdif_f = np.zeros((nlin,npix,niopw),dtype=np.float64) #rel norm diff in Rrs_f due to [aph, ag, ad, bbp]

    BLOCKSIZE = 16# 16 #32 #32 #256
    # --- Define a reference to the __global__ function and call it
    gpu_rhorc_fitting = mod.get_function("gpu_rhorc_fitting_onestep")
    bDim  = (BLOCKSIZE, BLOCKSIZE, 1)
    gridDim   = (iDivUp(npix, BLOCKSIZE), iDivUp(nlin, BLOCKSIZE), 1) ## Caution (ncol, nrow)!
    print(mask)

    gpu_rhorc_fitting(cuda.Out(iop),cuda.Out(rhorc_mod),cuda.Out(Rrs_mod),cuda.Out(relerr),cuda.Out(niter), cuda.Out(Rrs_out),\
        cuda.Out(iop_f),cuda.Out(Rrs_mod_f),cuda.Out(relerr_f),cuda.Out(niter_f), cuda.Out(relnormdif_f),\
        cuda.In(rhorc), cuda.In(LUTratio), cuda.In(amratio), cuda.In(mask),
        np.int32(nlin), np.int32(npix),
        block = bDim, grid = gridDim )

    cuda.Context.synchronize()

    print('iop= ',' '.join(f'{_:.7f}' for _ in iop[0,0,:]))
    print(relerr)
    print(niter)


    aero_all=[
        [1.316, 1.219, 1.122, 1.089, 1.063, 1.034, 1.0], #//wave ^(-0.5)
        [0.617, 0.81, 0.953, 1.034, 1.021, 1.089, 1.0] #//glint
        ]

    aero_all=np.array(aero_all)
    na=aero_all.shape[0]
    for ia in range(na):
        aero_all[ia,:]=aero_all[ia,:]*_r
    
    transFix=[1., 1., 1., 1., 1.,  1.,1.]
    transFix=np.array(transFix)
    wave_all=[483.2, 562.4, 664.6, 704.8, 739.2, 781.9, 836.6]
    wave_all=np.array(wave_all)
    wave_fit=wave_all[bds]
    f=plt.figure()
    ax=f.add_subplot(111)
    plt.xlim(350, 900)#2000)#900)
	# plt.ylim(0, np.amax(rrsdata)*1.2)
	#plt.yscale('log')
    plt.xlabel('wavelength (nm)')
    plt.ylabel('rhorc (1/sr)')
    plt.plot(wave_all, rhorc_all,'-+', color='r', label='input')
    plt.plot(wave_fit, rhorc_mod[0,0,:],'-o',mfc='none', color='b', label='fit')
    rhoa_ = np.zeros(len(wave_all))
    for ia in range(na):
        rhoa_=rhoa_+iop[0,0,4+ia]*aero_all[ia,:]
    # print( ','.join([f'{_:0.3f}' for _ in rhoa_/rhoa_[11]]) ) 
    print('rhoa= ',' '.join(f'{_:.5f}' for _ in rhoa_))
    plt.plot(wave_all, rhoa_)
    # plt.plot(wave_all, rhorc_all-rhoa_,'-s',mfc='none', color='orange',label='rhow*tr')
    tr=transFix**amratio[0,0]
    rhowTOA=(rhorc_all-rhoa_)
    rhow=rhowTOA/tr
    print('pi*Rrs= ',' '.join(f'{_:.5f}' for _ in rhow))
    print('Rrs= ',' '.join(f'{_:.5f}' for _ in rhow/np.pi))
    plt.plot(wave_all, rhow,'-o',mfc='none', color='orange',label='rhow')
    # plt.plot(wave_all, rhorc_all-rhoa_/rhoa_[11]*0.035,'-+', color='orange')
    # print(f'{Rrs-_err}')
    # plt.title(title)
    plt.text(0.2,0.65,'aph440, ag440, afl, bbp550\n'+' '.join(f'{_:.4f}' for _ in iop[0,0,:]), transform=ax.transAxes)
    plt.legend()
    # plt.savefig(title+'.png')
    plt.show()
