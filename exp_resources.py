from plotting.plots import *

import math


class DataHandling:

    def __init__(self):
        print("Initializing " + self.__class__.__name__)
        self.load_data()
        for var in scaling_variables:
            self.scale(var)
        #self.mix_otp_bike()

    def load_data(self):
        print("Loading data")
        self.neighborhood_se = pd.read_csv(filepath_or_buffer=path_neighborhood_se, sep=';', index_col=0)
        self.flows = pd.read_csv(filepath_or_buffer=path_flows, sep=';', index_col=0)
        self.bike = pd.read_csv(filepath_or_buffer=path_bike_matrix, sep=';', index_col=0)
        #self.pt = pd.read_csv(filepath_or_buffer=path_pt_matrix, sep=';', index_col=0)
        self.otp = pd.read_csv(filepath_or_buffer=path_otp_matrix, sep=';', index_col=0)
        self.euclid = pd.read_csv(filepath_or_buffer=path_euclid_matrix, sep=';', index_col=0)

    def matrices(self):
        self.flows = self.reduce_matrix(self.flows)
        self.bike = self.reduce_matrix(self.bike)
        self.otp = self.reduce_matrix(self.otp)
        self.euclid = self.reduce_matrix(self.euclid)

    def mix_otp_bike(self):
        short = np.asarray(self.euclid < short_trip).nonzero()
        self.mixed = self.otp
        for i, j in enumerate(short[0]):
            self.mixed[j, short[1][i]] = self.bike[j, short[1][i]]

    def scale(self, variable):
        max_val = max(self.neighborhood_se[variable])
        scaled = [100.0*(each/max_val) for each in self.neighborhood_se[variable]]
        self.neighborhood_se[variable + '_scaled'] = scaled

    def build_speed_vector(self, variable, euclid, name):
        speed = []
        for i, each in enumerate(euclid):
            speed = (each*1000.0)/(variable[i]/60.0)
            speed.append(speed)

        #pickle.dump(np.array(speed), open(name + "_speed.p", "wb"))

    def reduce_matrix(self, frame):
        matrix = np.triu(m=frame.to_numpy(), k=0)
        matrix[matrix == 0] = np.nan
        return matrix



class Skater:

    def __init__(self):
        print("Initializing " + self.__class__.__name__)
        handler = DataHandling()
        # areas into geopandas DataFrame
        self.geo_df = geopandas.GeoDataFrame(crs=crs_proj,
                                             geometry=geopandas.GeoSeries.from_wkt(handler.neighborhood_se.geometry))
        # self.geo_df['lon'] = self.geo_df['centroid'].apply(lambda p: p.x)
        # self.geo_df['lat'] = self.geo_df['centroid'].apply(lambda p: p.y)

        self.pos = {}
        self.adj_g = []
        self.geo_pos()

        # create DataFrame containing relevant socio-economic variables for the model
        self.model_df = handler.neighborhood_se[model_variables]

    def geo_pos(self):
        # get positions of nodes to make the graph spatial
        for count, elem in enumerate(np.array(self.geo_df.centroid)):
            self.pos[self.geo_df.index[count]] = (elem.x, elem.y)

    def remove_islands(self):
        # connect spatially disconnected subgraphs
        # find connected components of the graph and create subgraphs
        S = [self.adj_g.subgraph(c).copy() for c in nx.connected_components(self.adj_g)]
        # only connect if there are disconnected subgraphs
        while len(S) != 1:
            # get index of largest connected component
            largest_cc = np.argmax([len(graph.nodes()) for graph in S])
            # iterate over subgraphs except the largest component
            for subgraph in S[:largest_cc] + S[largest_cc + 1:]:
                subgraph_dist = []
                # declare space of possible connection by considering all nodes outside the current subgraph
                candidate_space = self.adj_g.copy()
                candidate_space.remove_nodes_from(subgraph.nodes())
                # determine number of connections by fraction of subgraph size
                no_connections = math.ceil(len(subgraph.nodes()) / 3)
                for node in subgraph.nodes():
                    # get list of dictionaries with the connected point outside the subgraph as key and distance as value
                    node_dist_dicts = [{dest_point: Point(self.pos[dest_point]).distance(Point(self.pos[node]))}
                                       for dest_point in candidate_space.nodes()]
                    # flatten value list
                    dist_list = [list(dict.values()) for dict in node_dist_dicts]
                    dist_list = np.array([item for sublist in dist_list for item in sublist])
                    # get the determined number of shortest possible connections
                    min_dist = np.argsort(dist_list)[:no_connections]
                    for dist_ind in min_dist:
                        subgraph_dist.append([node,
                                              np.fromiter(node_dist_dicts[dist_ind].keys(), dtype='U4'),
                                              np.fromiter(node_dist_dicts[dist_ind].values(), dtype=float)])
                min_dist_ind = np.argsort(np.array(subgraph_dist, dtype=object)[:, 2])[:no_connections]
                # add edge to connect disconnected subgraphs
                for ind in min_dist_ind:
                    self.adj_g.add_edge(u_of_edge=subgraph_dist[ind][0],
                                   v_of_edge=subgraph_dist[ind][1][0],
                                   cost=subgraph_dist[ind][2][0])
            S = [self.adj_g.subgraph(c).copy() for c in nx.connected_components(self.adj_g)]

    def adjacency_graph(self):
        # create adjacency matrix for all areas

        # check for invalid polygons and apply simple fix according to https://stackoverflow.com/questions/20833344/fix-invalid-polygon-in-shapely
        for i, pol in enumerate(self.geo_df.geometry):
            if not pol.is_valid:
                self.geo_df.geometry[i] = pol.buffer(0)

        mat = np.invert(np.array([self.geo_df.geometry.disjoint(pol) for pol in self.geo_df.geometry]))
        # correct for self-loops
        np.fill_diagonal(a=mat, val=False)
        # boolean matrix into networkx graph
        self.adj_g = nx.convert_matrix.from_numpy_array(A=mat)
        # dict index and name of areas
        area_dict = {}
        for i, area in enumerate(np.array(self.geo_df.index)):
            area_dict[i] = area
        # relabel nodes to area identifier
        self.adj_g = nx.relabel.relabel_nodes(G=self.adj_g, mapping=area_dict)
        self.remove_islands()


    # Minimal Spanning Tree Clustering according to https://doi.org/10.1080/13658810600665111
    def mst(self):
        print('Create MST')
        # get adjacency graph
        self.adjacency_graph()

        # iterate over all graph edges to assign a cost
        for u, v in self.adj_g.edges():
            # euclidean distance between attribute vectors
            dist = np.nansum([(self.model_df.loc[u][col] - self.model_df.loc[v][col])**2 for col in range(len(self.model_df.columns.values))])
            self.adj_g[u][v]['cost'] = dist

        mst = nx.algorithms.tree.mst.minimum_spanning_tree(G=self.adj_g, weight='cost', algorithm='prim')
        """    
        # MST generation
        v_1 = np.random.randint(low=0, high=len(model_df))
        mst = nx.Graph()
        mst.add_node(node_for_adding=np.array(model_df.index)[v_1])
        while len(mst.nodes()) <= len(model_df):
            # identify potential candidates by checking for all edges of all vertices currently in the MST
            candidates = np.array(list(graph.edges(mst.nodes(), data=True)))
            # remove edges leading to vertices already in the MST
            candidates = candidates[np.invert(np.in1d(candidates[:, 1], np.array(list(mst.nodes()))))]
            cost_list = [candidate['cost'] for candidate in candidates[:, 2]]
            min_ind = np.argmin(cost_list)
            mst.add_node(node_for_adding=candidates[min_ind][1])
            mst.add_edge(u_of_edge=candidates[min_ind][0], v_of_edge=candidates[min_ind][1])
            print(len(mst.nodes()))
        """
        return mst

    # calculating the intracluster square deviation ("sum of square deviations", SSD)
    def ssd(self, k, x):
        # initialize the SSD
        ssd_k = 0.0
        # get average for all attributes
        attributes_av = [x[col].mean() for col in x.columns]
        # iterate over nodes in tree k
        for i in list(k.nodes()):
            # add SD of each node in tree k to SSD
            ssd_k += np.nansum([(x.loc[i][j] - attributes_av[j]) ** 2 for j in range(len(x.columns))])
        return ssd_k

    # objective function 1 and balancing function
    def objective_functions(self, ssd_t, t_a, t_b):
        ssd_t_a = self.ssd(k=t_a, x=self.model_df.loc[list(t_a.nodes())])
        ssd_t_b = self.ssd(k=t_b, x=self.model_df.loc[list(t_b.nodes())])
        f = ssd_t-(ssd_t_a+ssd_t_b)
        f_2 = min((ssd_t - ssd_t_a), (ssd_t - ssd_t_b))
        return f, f_2

    # solution creation by removing an edge l
    def potential_solution(self, edges, graph):
        s_p = []
        for l in edges:
            mst_copy = graph.copy()
            mst_copy.remove_edge(l[0], l[1])
            split = [graph.subgraph(c).copy() for c in nx.connected_components(mst_copy)]
            s_p.append(split)
        return s_p

    def tree_patitioning(self, c):
        print('Start tree partitioning')
        components = [self.mst()]
        sc = 20

        for clust in range(c):
            best_edges = []
            best_edges_values = []
            print('Test component for split')
            for t in components:
                # get all possible solutions for finding the starting vertice by iteration over all edges of the MST
                s_p_1 = self.potential_solution(edges=t.edges(), graph=t)
                # calculate difference in number of vertices between two subtrees of a possible split
                split_dif = [(abs(len(split[0].nodes()) - len(split[1].nodes()))) for split in s_p_1]
                # edge/vertex that best splits the MST into two subtrees of similar size
                if len(split_dif) == 0:
                    v_c = list(t.nodes())[0]
                else:
                    split_edge = list(t.edges())[np.argmin(split_dif)]
                    v_c = split_edge[0]

                # Step 1
                # get possible solutions s_p for all edges incident to v_c
                s_p_edges = list(t.edges(v_c))
                n = 0
                n_star = 0
                f_s_star = 0

                list_l = {}
                edges_expanded = []
                while n - n_star <= sc:
                    # Step 2
                    if len(s_p_edges) == 0:
                        break
                    f1_list = []
                    s_p = self.potential_solution(edges=s_p_edges, graph=t)
                    ssd_t = self.ssd(k=t, x=self.model_df.loc[list(t.nodes())])
                    for i, s in enumerate(s_p):
                        f, f_2 = self.objective_functions(ssd_t=ssd_t, t_a=s[0], t_b=s[1])
                        list_l[s_p_edges[i]] = f_2
                        f1_list.append(f)
                    f1_s_j = max(f1_list)

                    # Step 3
                    if f1_s_j > f_s_star:
                        s_star = s_p_edges[np.argmax(f1_list)]
                        f_s_star = f1_s_j
                        n_star = n
                        print('new best solution at n= ' + str(n))
                    n += 1

                    # Step 4
                    next = list(list_l.keys())[np.argmin(list(list_l.values()))]
                    if next in set(edges_expanded):
                        print('something is weird')
                    edges_expanded.append(next)
                    del list_l[next]
                    s_p_edges = list(set(list(t.edges(next[0])) + list(t.edges(next[1]))) - set(edges_expanded))

                best_edges.append(s_star)
                best_edges_values.append(f_s_star)
            best_ind = np.argmax(best_edges_values)
            best_edge = best_edges[best_ind]
            components[best_ind].remove_edge(best_edge[0], best_edge[1])
            components.extend([components[best_ind].subgraph(c).copy() for c in nx.connected_components(components[best_ind])])
            del components[best_ind]

        return components












# def filter_shorttrips():
#     walked = handler.reduce_matrix(frame=handler.bike)
#     walked = np.where(walked < short_trip)
#     walked_graph = nx.Graph()
#     index_list = list(handler.neighborhood_se.index)
#     reduced_otp = handler.reduce_matrix(frame=handler.otp)
#     reduced_pt = handler.reduce_matrix(frame=handler.pt)
#     reduced_bike = handler.reduce_matrix(frame=handler.bike)
#     for i, or_ind in enumerate(walked[0]):
#         dest_ind = walked[1][i]
#         walked_graph.add_edge(u_of_edge=index_list[or_ind], v_of_edge=index_list[dest_ind])
#         reduced_pt[or_ind][dest_ind] = np.nan
#         reduced_otp[or_ind][dest_ind] = np.nan
#         reduced_bike[or_ind][dest_ind] = np.nan
#
#     reduced_otp = np.floor(reduced_otp/60.)*60.
#     time_frame = pd.concat([pd.DataFrame(reduced_otp[~np.isnan(reduced_otp)], columns=['otp']),
#                             pd.DataFrame(reduced_pt[~np.isnan(reduced_pt)], columns=['pt'])], axis=1)
#
#     #comp_hist(frame=time_frame, colors=['red', 'blue'])
#     #plt.hist(reduced_pt[~np.isnan(reduced_pt)], bins=50, fc=(0, 0, 1, 0.5))
#     # floor_diff = abs(reduced_otp-reduced_pt)
#     # floor_diff_pt = floor_diff/reduced_pt
#     # floor_diff_pt = floor_diff_pt[~np.isnan(floor_diff_pt)]
#     # floor_diff_otp = floor_diff/reduced_otp
#     # floor_diff_otp = floor_diff_otp[~np.isnan(floor_diff_otp)]
#     # plt.hist(floor_diff_pt, bins=70, range=(0, 1))
#     # plt.tight_layout()
#     # plt.savefig(fname=os.path.join(path_explore, 'pt_diff3'))
#     # plt.close()
#     # plt.hist(floor_diff_otp, bins=70, range=(0, 1))
#     # plt.tight_layout()
#     # plt.savefig(fname=os.path.join(path_explore, 'pt_diff4'))
#     # plt.close()
#
#     a = 10
#
#     geo_df = geopandas.GeoDataFrame(crs=crs_proj,
#                                     geometry=geopandas.GeoSeries.from_wkt(handler.neighborhood_se.geometry))
#     geo_net_plot(geo_frame=geo_df, graph=walked_graph)
#     a=1





def hist_cluster():
    cluster_list = {'pt_all': 'blue',

                    'pt_rel': 'red'
                    }

    f, ax = plt.subplots(figsize=(7, 5))
    sns.despine(f)
    clusters = pd.read_csv(filepath_or_buffer=path_clustercoeff, sep=';')
    for cluster in cluster_list:
        sns.histplot(data=clusters, x=cluster, color=cluster_list[cluster], binwidth=0.025, label=cluster, alpha=0.6)
    ax.set_title('Clustering coefficient for Public Transport')
    plt.xlabel('Clustering coefficient')
    ax.margins(x=0)
    plt.tight_layout()
    plt.legend()
    plt.savefig(fname=os.path.join(path_hists, 'cluster_hist'))
    plt.close(f)



def plot_se_kmean():
    geo_frame = se_kmean()

    fig, ax = plt.subplots(figsize=(20, 15))
    geo_frame.plot(column='clust', legend=True, cmap='viridis_r', ax=ax)
    ax.set_title('KMean Cluster for Socio-economic data')
    plt.savefig(fname=os.path.join(path_maps, 'kmean_cluster'))







def plot_adj_mat(c):
    skat = Skater()
    comp = skat.tree_patitioning(c)

    fig, ax = plt.subplots(figsize=(20, 15))
    skat.geo_df.plot(ax=ax)
    # nx.drawing.nx_pylab.draw_networkx_edges(G=comp, pos=skat.pos, ax=ax)

    for component in comp:
        nx.drawing.nx_pylab.draw_networkx_edges(G=component, pos=skat.pos, ax=ax)
    plt.show()
    plt.close(fig=fig)
    for i in range(c):
        a = list(comp[i].nodes())
        for node in a:
            skat.geo_df.at[node, 'clust'] = i
    fig, ax = plt.subplots(figsize=(20, 15))
    skat.geo_df.plot(ax=ax, column='clust')
    plt.show()
    a =10




# hist_scaled_se()
# clusters = get_cluster()
# hist_cluster()
# plot_se_kmean()

# plot_adj_mat()