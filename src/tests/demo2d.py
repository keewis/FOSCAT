import numpy as np
import os, sys
import matplotlib.pyplot as plt
import healpy as hp
import getopt

#=================================================================================
# INITIALIZE FoCUS class
#=================================================================================
import foscat.Synthesis as synthe

def usage():
    print(' This software is a demo of the foscat library:')
    print('>python demo2d.py -n=8 [-c|--cov][-s|--steps=3000][-S=1234|--seed=1234][-x|--xstat][-p|--p00][-g|--gauss][-k|--k5x5][-d|--data][-o|--out]')
    print('-n : is the n of the input map (nxn)')
    print('--cov (optional): use scat_cov instead of scat.')
    print('--steps (optional): number of iteration, if not specified 1000.')
    print('--seed  (optional): seed of the random generator.')
    print('--xstat (optional): work with cross statistics.')
    print('--p00   (optional): Loss only computed on p00.')
    print('--gauss (optional): convert Venus map in gaussian field.')
    print('--k5x5  (optional): Work with a 5x5 kernel instead of a 3x3.')
    print('--data  (optional): If not specified use Venu_256.npy.')
    print('--out   (optional): If not specified save in *_demo_*.')
    exit(0)
    
def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "n:cS:s:xpgkd:o:", \
                                   ["nside", "cov","seed","steps","xstat","p00","gauss","k5x5","data","out"])
    except getopt.GetoptError as err:
        # print help information and exit:
        print(err)  # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    cov=False
    nside=-1
    nstep=1000
    docross=False
    dop00=False
    dogauss=False
    KERNELSZ=3
    seed=1234
    outname='demo'
    data="TURBU.npy"
    
    for o, a in opts:
        if o in ("-c","--cov"):
            cov = True
        elif o in ("-n", "--nside"):
            nside=int(a[1:])
        elif o in ("-s", "--steps"):
            nstep=int(a[1:])
        elif o in ("-S", "--seed"):
            seed=int(a[1:])
            print('Use SEED = ',seed)
        elif o in ("-o", "--out"):
            outname=a[1:]
            print('Save data in ',outname)
        elif o in ("-d", "--data"):
            data=a[1:]
            print('Read data from ',data)
        elif o in ("-x", "--xstat"):
            docross=True
        elif o in ("-g", "--gauss"):
            dogauss=True
        elif o in ("-k", "--k5x5"):
            KERNELSZ=5
        elif o in ("-p", "--p00"):
            dop00=True
        else:
            assert False, "unhandled option"

    if nside<2 or nside!=2**(int(np.log(nside)/np.log(2))) or nside>2048:
        print('n should be a power of 2 and in [2,...,2048]')
        usage()
        exit(0)

    print('Work with n=%d'%(nside))

    if cov:
        import foscat.scat_cov as sc
        print('Work with ScatCov')
    else:
        import foscat.scat as sc
        print('Work with Scat')
        
    #=================================================================================
    # DEFINE A PATH FOR scratch data
    # The data are storred using a default nside to minimize the needed storage
    #=================================================================================
    scratch_path = '../data'

    #=================================================================================
    # Get data
    #=================================================================================
    im=np.load(data)
    im=im[im.shape[0]//2-nside//2:im.shape[0]//2+nside//2,im.shape[1]//2-nside//2:im.shape[1]//2+nside//2]

    mask=np.ones([1,nside,nside])
    mask[0,:,:]=np.isnan(im)==False
    mask[0,0:nside//4,:]=0.0
    mask[0,-nside//4:,:]=0.0
    mask[0,:,0:nside//4]=0.0
    mask[0,:,-nside//4:]=0.0
    im[np.isnan(im)]=np.median(im[np.isnan(im)==False])
    im=im-np.median(im)
    im=im/im.std()
    print(im.shape)
    #=================================================================================
    # Generate a random noise with the same coloured than the input data
    #=================================================================================

    lam=1.2
    if KERNELSZ==5:
        lam=1.0

    #=================================================================================
    # COMPUTE THE WAVELET TRANSFORM OF THE REFERENCE MAP
    #=================================================================================
    scat_op=sc.funct(NORIENT=4,          # define the number of wavelet orientation
                     KERNELSZ=KERNELSZ,  # define the kernel size
                     OSTEP=0,           # get very large scale (nside=1)
                     LAMBDA=lam,
                     TEMPLATE_PATH=scratch_path,
                     slope=1.0,
                     gpupos=2,
                     use_R_format=True,
                     chans=1,
                     SHOWGPU=True,
                     all_type='float64')
    
    #=================================================================================
    # DEFINE A LOSS FUNCTION AND THE SYNTHESIS
    #=================================================================================
    
    def lossX(x,scat_operator,args):
        
        ref = args[0]
        im  = args[1]
        mask = args[2]

        if docross:
            learn=scat_operator.eval(im,image2=x,Imaginary=True,mask=mask)
        else:
            learn=scat_operator.eval(x,mask=mask)
            
        if dop00:
            loss=scat_operator.bk_reduce_mean(scat_operator.bk_square(ref.P00[0,0,:]-learn.P00[0,0,:]))
        else:
            loss=scat_operator.reduce_sum(scat_operator.square(ref-learn))

        return(loss)

    def loss_norm(x,scat_operator,args):
        
        im = args[0]
        
        ims = scat_op.up_grade(scat_op.ud_grade_2(scat_op.ud_grade_2(im)),nside)
        xs = scat_op.up_grade(scat_op.ud_grade_2(scat_op.ud_grade_2(x)),nside)
        
        return scat_operator.bk_reduce_sum(scat_operator.bk_square(ims-xs.get_data()))

    if docross:
        refX=scat_op.eval(im,image2=im,Imaginary=True,mask=mask)
    else:
        refX=scat_op.eval(im,mask=mask)

    loss1=synthe.Loss(lossX,scat_op,refX,im,mask)
    loss2=synthe.Loss(loss_norm,scat_op,im)
        
    sy = synthe.Synthesis([loss1])
    #=================================================================================
    # RUN ON SYNTHESIS
    #=================================================================================
    np.random.seed(seed)
    
    imap=scat_op.up_grade(scat_op.ud_grade_2(scat_op.ud_grade_2(im)),nside).numpy()
    
    omap=sy.run(imap,
                DECAY_RATE=0.9995,
                NUM_EPOCHS = nstep,
                LEARNING_RATE = 0.01,
                EPSILON = 1E-15)

    #=================================================================================
    # STORE RESULTS
    #=================================================================================
    if docross:
        start=scat_op.eval(im,image2=imap,mask=mask)
        out =scat_op.eval(im,image2=omap,mask=mask)
    else:
        start=scat_op.eval(imap,mask=mask)
        out =scat_op.eval(omap,mask=mask)
    
    np.save('in2d_%s_map_%d.npy'%(outname,nside),im)
    np.save('st2d_%s_map_%d.npy'%(outname,nside),imap)
    np.save('out2d_%s_map_%d.npy'%(outname,nside),omap)
    np.save('mask_%s_map_%d.npy'%(outname,nside),mask)
    np.save('out2d_%s_log_%d.npy'%(outname,nside),sy.get_history())

    refX.save('in2d_%s_%d'%(outname,nside))
    start.save('st2d_%s_%d'%(outname,nside))
    out.save('out2d_%s_%d'%(outname,nside))

    print('Computation Done')
    sys.stdout.flush()

if __name__ == "__main__":
    main()


    
