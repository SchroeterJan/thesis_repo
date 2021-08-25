from processors import *
from config import *


def areas():
    se_prep = SENeighborhoods()

    # crop socio-economic data to relevant year and areas
    se_prep.crop_se(year=se_year)
    se_prep.geo_data = se_prep.geo_data.set_index(keys=column_names['geo_id_col'], drop=False)
    se_prep.filter_areas()

    # keep only relevant socio-economic variables
    for variable in census_variables:
        se_prep.extract_var(var=variable)


    # check if prepared data already exists
    if os.path.isfile(path_neighborhood_se):
        print('removing existing Neighborhood SE Data')
        os.remove(path_neighborhood_se)
    # write resulting data set to disk
    print('writing preprocessed data to disk')
    se_prep.geo_data.to_csv(path_or_buf=path_neighborhood_se, index=True, index_label='Buurt_code', sep=';')


def bike_times():
    trans_prep = TransportPrep()
    if not os.path.isfile(path_bike_scrape):
        print('Gather bike times\n Make sure GH server is running!')
        trans_prep.get_gh_times()

    bike_time = trans_prep.order_times()
    bike_time.to_csv(path_or_buf=os.path.join(path_repo, path_generated, 'Bike_times_GH.csv'), sep=';')


def flows():
    flow_prep = PassengerCounts()
    flow_prep.area_stop_matching()
    flow_prep.filter_connections()
    area_flow_matrix = flow_prep.assign_passcounts()

    print('Writing flow matrix to disk')
    if os.path.isfile(path_flows):
        print('removing existing flow Data')
        os.remove(path_flows)
    area_flow_matrix.to_csv(path_or_buf=path_flows, sep=';')


areas()
# flows()
# bike_times()
